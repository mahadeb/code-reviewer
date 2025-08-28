import subprocess
import sys
import config

if config.MODEL_PROVIDER == "openai":
    from langchain_openai import ChatOpenAI
    from langchain.prompts import PromptTemplate
    from langchain.chains import LLMChain
elif config.MODEL_PROVIDER == "gemini":
    import google.generativeai as genai

def get_latest_diff(repo_path):
    cmd = ['git', '-C', repo_path, 'diff', 'HEAD~1', 'HEAD']
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.stdout

template = """
You are a senior code reviewer. Review the following git diff and give suggestions:

{diff}

Reply in bullet points.
"""

def gemini_review(diff_text):
    genai.configure(api_key=config.GEMINI_API_KEY)
    model = genai.GenerativeModel('gemini-1.5-flash')
    prompt_text = template.replace("{diff}", diff_text)
    response = model.generate_content(prompt_text)
    return response.text if hasattr(response, 'text') else str(response)
def openai_review(diff_text):
    prompt_obj = PromptTemplate.from_template(template)
    llm = ChatOpenAI(model_name="gpt-3.5-turbo", temperature=0, openai_api_key=config.OPENAI_API_KEY)
    chain = LLMChain(prompt=prompt_obj, llm=llm)
    response = chain.invoke({"diff": diff_text})
    return response["text"] if isinstance(response, dict) and "text" in response else response
def main():
    repo_path = sys.argv[1] if len(sys.argv) > 1 else "."
    diff_text = get_latest_diff(repo_path)
    if not diff_text.strip():
        print("No code changes detected in the latest commit of the repo.")
        return
    if config.MODEL_PROVIDER == "openai":
        response = openai_review(diff_text)
        print(f"\nOpenAI Code Review Suggestions for repo: {repo_path}\n")
        print(response)
    elif config.MODEL_PROVIDER == "gemini":
        response = gemini_review(diff_text)
        print(f"\nGemini Code Review Suggestions for repo: {repo_path}\n")
        print(response)
if __name__ == "__main__":
    main()
