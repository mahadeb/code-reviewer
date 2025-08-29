from flask import Flask, request, jsonify
import requests
import os
import config

app = Flask(__name__)

# 🔧 Config
GITLAB_API = config.GITLAB_API
GITLAB_TOKEN = config.GITLAB_TOKEN
MODEL_PROVIDER = config.MODEL_PROVIDER
OPENAI_API_KEY = config.OPENAI_API_KEY
GEMINI_API_KEY = config.GEMINI_API_KEY

if MODEL_PROVIDER == "openai":
    import openai
    openai.api_key = OPENAI_API_KEY
elif MODEL_PROVIDER == "gemini":
    import google.generativeai as genai
    genai.configure(api_key=GEMINI_API_KEY)

template = """
You are a senior reviewer. Review this Git diff from {file_path}.
Suggest issues in JSON format:
[{{"line": <line_number>, "comment": "<suggestion>"}}]
Diff:
{diff}
"""


def gemini_review(file_path, diff):
    model = genai.GenerativeModel('gemini-1.5-flash')
    prompt_text = template.format(file_path=file_path, diff=diff)
    response = model.generate_content(prompt_text)
    return response.text if hasattr(response, 'text') else str(response)


def openai_review(file_path, diff):
    prompt = template.format(file_path=file_path, diff=diff)
    response = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=[{"role": "user", "content": prompt}],
        temperature=0
    )
    return response["choices"][0]["message"]["content"]


def review_diff(file_path, diff):
    if MODEL_PROVIDER == "openai":
        return openai_review(file_path, diff)
    elif MODEL_PROVIDER == "gemini":
        return gemini_review(file_path, diff)
    else:
        return "No valid MODEL_PROVIDER configured."

@app.route("/webhook", methods=["POST"])
def gitlab_webhook():
    event = request.json

    # Only handle merge requests
    if event.get("object_kind") != "merge_request":
        return jsonify({"status": "ignored"})

    project_id = event["project"]["id"]
    mr_iid = event["object_attributes"]["iid"]


    # 1️⃣ Get MR changes and diff_refs
    url = f"{GITLAB_API}/projects/{project_id}/merge_requests/{mr_iid}/changes"
    headers = {"PRIVATE-TOKEN": GITLAB_TOKEN}
    changes = requests.get(url, headers=headers).json()
    # Get diff_refs from MR details API
    mr_url = f"{GITLAB_API}/projects/{project_id}/merge_requests/{mr_iid}"
    mr_details = requests.get(mr_url, headers=headers).json()
    diff_refs = mr_details.get("diff_refs", {})

    # 2️⃣ Review each file
    for change in changes.get("changes", []):
        if "diff" not in change:
            continue
        file_path = change["new_path"]
        diff = change["diff"]

        suggestions = review_diff(file_path, diff)

        # 3️⃣ Post inline comments as MR discussions

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
            requests.post(note_url, headers=headers, json=payload)
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
            resp = requests.post(discussion_url, headers=headers, json=discussion_payload)
            if resp.status_code >= 400:
                print(f"[ERROR] Failed to post inline comment: {resp.text}")

    return jsonify({"status": "ok"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001)