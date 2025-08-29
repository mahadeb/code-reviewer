from flask import Flask, request, jsonify
import requests
import os
import config
import threading
from datetime import datetime, timezone

app = Flask(__name__)

# 🔧 Config
GITLAB_API = config.GITLAB_API
GITLAB_TOKEN = config.GITLAB_TOKEN
MODEL_PROVIDER = config.MODEL_PROVIDER
OPENAI_API_KEY = config.OPENAI_API_KEY
GEMINI_API_KEY = config.GEMINI_API_KEY
OPENAI_MODEL = config.OPENAI_MODEL
GEMINI_MODEL = config.GEMINI_MODEL

if MODEL_PROVIDER == "openai":
    from openai import OpenAI
    openai_client = OpenAI(api_key=OPENAI_API_KEY)
elif MODEL_PROVIDER == "gemini":
    import google.generativeai as genai
    genai.configure(api_key=GEMINI_API_KEY)

template = """
You are a senior reviewer. Review this Git diff from {file_path}.
Suggest issues in JSON format:
[{"line": <line_number>, "comment": "<suggestion>"}]
Diff:
{diff}
"""

# In-memory status for the last background job (best-effort)
LAST_JOB_STATUS = {
    "started_at": None,
    "finished_at": None,
    "status": "idle",  # idle|running|completed|error
    "project_id": None,
    "mr_iid": None,
    "files_reviewed": 0,
    "comments_posted": 0,
    "errors": [],
}


def gemini_review(file_path, diff):
    model = genai.GenerativeModel(GEMINI_MODEL)
    # Use string replacement to avoid KeyError with curly braces in diff
    prompt_text = template.replace("{file_path}", file_path).replace("{diff}", diff)
    try:
        response = model.generate_content(prompt_text)
        result = response.text if hasattr(response, 'text') else str(response)
        print(f"[GEMINI] Response for {file_path}: {result[:300]}...")
        return result
    except Exception as e:
        error_str = str(e)
        if "429" in error_str or "ResourceExhausted" in error_str:
            print(f"[GEMINI] Rate limit exceeded for {file_path}: {error_str}")
            # Could implement fallback to OpenAI here if configured
            return False
        else:
            print(f"Gemini error: {e}")
            return False


def openai_review(file_path, diff):
    # Use string replacement to avoid KeyError with curly braces in diff
    prompt = template.replace("{file_path}", file_path).replace("{diff}", diff)
    print(f"[OPENAI] Making API call for {file_path} with model {OPENAI_MODEL}")
    try:
        response = openai_client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0
        )
        print(f"[OPENAI] Response: {response}")
        result = response.choices[0].message.content
        print(f"[OPENAI] Response for {file_path}: {result[:300]}...")
        return result
    except Exception as e:
        print(f"OpenAI error: {e}")
        return False


def review_diff(file_path, diff):
    try:
        print(f"[REVIEW_DIFF] Starting review for {file_path} with provider: {MODEL_PROVIDER}")
        print(f"[REVIEW_DIFF] Diff length: {len(diff) if diff else 0}")
        
        if MODEL_PROVIDER == "openai":
            print(f"[REVIEW_DIFF] Calling openai_review")
            return openai_review(file_path, diff)
        elif MODEL_PROVIDER == "gemini":
            print(f"[REVIEW_DIFF] Calling gemini_review")
            result = gemini_review(file_path, diff)
            # If Gemini fails due to rate limit and OpenAI is available, try fallback
            if result is False and OPENAI_API_KEY and OPENAI_API_KEY.strip():
                print(f"[REVIEW_DIFF] Gemini failed, trying OpenAI fallback for {file_path}")
                return openai_review(file_path, diff)
            return result
        else:
            print(f"[REVIEW_DIFF] Invalid provider: {MODEL_PROVIDER}")
            return "No valid MODEL_PROVIDER configured."
    except Exception as e:
        print(f"Model review failed: {e}")
        import traceback
        print(f"[REVIEW_DIFF] Full traceback: {traceback.format_exc()}")
        return False

def process_mr_async(data):
    # heavy work: fetch MR diff, call Gemini/OpenAI, post comments
    try:
        if data.get("object_kind") != "merge_request":
            return

        project_id = data["project"]["id"]
        mr_iid = data["object_attributes"]["iid"]

        # Mark job started
        LAST_JOB_STATUS.update({
            "started_at": datetime.now(timezone.utc).isoformat(),
            "finished_at": None,
            "status": "running",
            "project_id": project_id,
            "mr_iid": mr_iid,
            "files_reviewed": 0,
            "comments_posted": 0,
            "errors": [],
        })
        print(f"[JOB] Start review: project={project_id} mr_iid={mr_iid}")

        headers = {"PRIVATE-TOKEN": GITLAB_TOKEN}

        # Get MR changes and diff_refs with reasonable timeouts
        url = f"{GITLAB_API}/projects/{project_id}/merge_requests/{mr_iid}/changes"
        mr_url = f"{GITLAB_API}/projects/{project_id}/merge_requests/{mr_iid}"

        changes_resp = requests.get(url, headers=headers, timeout=15)
        if changes_resp.status_code >= 400:
            print(f"[ERROR] Failed to fetch MR changes: {changes_resp.text}")
            try:
                LAST_JOB_STATUS["errors"].append(f"fetch_changes:{changes_resp.status_code}")
            except Exception:
                pass
            return
        changes = changes_resp.json()

        mr_details_resp = requests.get(mr_url, headers=headers, timeout=15)
        if mr_details_resp.status_code >= 400:
            print(f"[ERROR] Failed to fetch MR details: {mr_details_resp.text}")
            try:
                LAST_JOB_STATUS["errors"].append(f"fetch_details:{mr_details_resp.status_code}")
            except Exception:
                pass
            return
        mr_details = mr_details_resp.json()
        diff_refs = mr_details.get("diff_refs", {})

        # Review each file
        for change in changes.get("changes", []):
            if "diff" not in change:
                continue
            file_path = change.get("new_path") or change.get("old_path")
            diff = change["diff"]

            try:
                suggestions = review_diff(file_path, diff)
                # Skip to next file if no valid suggestions
                if not suggestions or suggestions.strip() == "":
                    print(f"[INFO] No suggestions for {file_path}, skipping")
                    continue
                # Debug: log what the model returned
                print(f"[DEBUG] Model response for {file_path}: {suggestions[:200]}...")
            except Exception as model_err:
                print(f"[ERROR] Model review failed: {model_err}")
                try:
                    LAST_JOB_STATUS["errors"].append(f"model_review:{file_path}")
                except Exception:
                    pass
                continue

            # Post inline comments as MR discussions
            try:
                import json, re
                # Remove code block markers if present
                suggestions_clean = re.sub(r"^```json|```$", "", suggestions.strip(), flags=re.MULTILINE).strip()
                suggestions_list = json.loads(suggestions_clean)
            except Exception as e:
                print(f"[ERROR] Could not parse suggestions as JSON: {e}\nSuggestions: {suggestions}")
                # fallback: post as summary note if suggestions are not valid JSON
                note_url = f"{GITLAB_API}/projects/{project_id}/merge_requests/{mr_iid}/notes"
                payload = {"body": f"🤖 AI Review for `{file_path}`:\n\n{suggestions}"}
                try:
                    requests.post(note_url, headers=headers, json=payload, timeout=15)
                    LAST_JOB_STATUS["files_reviewed"] += 1
                except Exception as post_err:
                    print(f"[ERROR] Failed to post fallback note: {post_err}")
                    try:
                        LAST_JOB_STATUS["errors"].append(f"fallback_note:{file_path}")
                    except Exception:
                        pass
                continue

            for suggestion in suggestions_list:
                line = suggestion.get("line")
                comment = suggestion.get("comment")
                if line is None or not comment:
                    continue
                discussion_url = f"{GITLAB_API}/projects/{project_id}/merge_requests/{mr_iid}/discussions"
                discussion_payload = {
                    "body": f"🤖 {comment}",
                    "position": {
                        "base_sha": diff_refs.get("base_sha"),
                        "start_sha": diff_refs.get("start_sha"),
                        "head_sha": diff_refs.get("head_sha"),
                        "position_type": "text",
                        "new_path": file_path,
                        "new_line": line
                    }
                }
                try:
                    resp = requests.post(discussion_url, headers=headers, json=discussion_payload, timeout=15)
                    if resp.status_code >= 400:
                        print(f"[ERROR] Failed to post inline comment: {resp.text}")
                        try:
                            LAST_JOB_STATUS["errors"].append(f"inline_comment:{file_path}:{line}")
                        except Exception:
                            pass
                    else:
                        LAST_JOB_STATUS["comments_posted"] += 1
                except Exception as post_err:
                    print(f"[ERROR] Exception posting inline comment: {post_err}")
                    try:
                        LAST_JOB_STATUS["errors"].append(f"inline_exception:{file_path}:{line}")
                    except Exception:
                        pass

            # Count this file as reviewed
            LAST_JOB_STATUS["files_reviewed"] += 1

        LAST_JOB_STATUS["status"] = "completed"
        LAST_JOB_STATUS["finished_at"] = datetime.now(timezone.utc).isoformat()
        print(f"[JOB] Completed review: project={project_id} mr_iid={mr_iid}")
    except Exception as e:
        print(f"[ERROR] Unexpected error in process_mr_async: {e}")
        try:
            LAST_JOB_STATUS["status"] = "error"
            LAST_JOB_STATUS["finished_at"] = datetime.now(timezone.utc).isoformat()
            LAST_JOB_STATUS["errors"].append(str(e))
        except Exception:
            pass

@app.route("/webhook", methods=["POST"])
def gitlab_webhook():
    event = request.json
    # Only handle merge requests; respond quickly and do work in background
    if not isinstance(event, dict):
        return jsonify({"status": "bad_request"}), 400
    if event.get("object_kind") != "merge_request":
        return jsonify({"status": "ignored"}), 200

    # Kick off background thread (or push to a proper queue in future)
    worker = threading.Thread(target=process_mr_async, args=(event,), daemon=True)
    worker.start()
    return jsonify({"status": "accepted"}), 202

@app.route("/status", methods=["GET"])
def status():
    # Return the last job status; useful to verify background processing
    return jsonify(LAST_JOB_STATUS), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001)