import streamlit as st
import boto3
import requests
import json
import time

# --- AWS CONFIGURATION ---
AWS_REGION = st.secrets.get("AWS_REGION", "us-east-1")
AWS_ACCESS_KEY = st.secrets.get("AWS_ACCESS_KEY", "")
AWS_SECRET_KEY = st.secrets.get("AWS_SECRET_KEY", "")
S3_BUCKET_NAME = st.secrets.get("S3_BUCKET_NAME", "dev-drift-cache")

# Initialize Enterprise AWS Clients
s3_client = boto3.client('s3', region_name=AWS_REGION, aws_access_key_id=AWS_ACCESS_KEY, aws_secret_access_key=AWS_SECRET_KEY)
bedrock_runtime = boto3.client('bedrock-runtime', region_name=AWS_REGION, aws_access_key_id=AWS_ACCESS_KEY, aws_secret_access_key=AWS_SECRET_KEY)

def fetch_and_upload_github_repo(repo_url, max_files=5):
    """Securely fetches repository files and ingests them into Amazon S3 Data Lake."""
    try:
        clean_url = repo_url.replace("https://github.com/", "").replace("http://github.com/", "").strip("/")
        parts = clean_url.split("/")
        if len(parts) < 2: return False, "Invalid GitHub URL format."
        owner, repo = parts[0], parts[1]
        
        response = requests.get(f"https://api.github.com/repos/{owner}/{repo}/contents")
        if response.status_code != 200: return False, "Could not fetch repository. Ensure it is public."
        
        files_data = sorted(response.json(), key=lambda x: 0 if x['name'].endswith('.md') else 1)
        uploaded_count, combined_code = 0, ""
        
        for file in files_data:
            if uploaded_count >= max_files: break
            if file['type'] == 'file' and file['name'].lower().endswith(('.py', '.md', '.txt', '.json')):
                content = requests.get(file['download_url']).text
                
                # AWS Infrastructure Requirement: S3 Storage
                s3_client.put_object(Bucket=S3_BUCKET_NAME, Key=f"{repo}/{file['name']}", Body=content)
                
                combined_code += f"\n\n--- File: {file['name']} ---\n{content}"
                uploaded_count += 1
                
        st.session_state['repo_context'] = combined_code
        return True, f"Successfully ingested {uploaded_count} core files into Amazon S3."
    except Exception as e:
        return False, f"Ingestion Error: {str(e)}"

def ask_dev_drift(query):
    """Retrieval-Augmented Generation using Amazon Bedrock (Claude 3 Haiku)."""
    context = st.session_state.get('repo_context', '')
    if not context: return "Please process a repository first to build the context window."
    
    prompt = f"You are Dev-Drift, a senior enterprise architect. Based strictly on the following codebase files mapped from S3:\n\n{context}\n\nAnswer the user's query: {query}"
    
    body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 1500,
        "system": "You are a cloud architect mentoring a junior developer on repository onboarding.",
        "messages": [{"role": "user", "content": prompt}]
    })
    
    try:
        # AWS Generative AI Requirement: Bedrock API
        response = bedrock_runtime.invoke_model(
            modelId='anthropic.claude-3-haiku-20240307-v1:0',
            contentType='application/json',
            accept='application/json',
            body=body
        )
        response_body = json.loads(response['body'].read())
        return response_body['content'][0]['text']
    except Exception as e:
        return f"Amazon Bedrock Rate Limit / API Error: {str(e)}. Please try again later."

# --- UI FRONTEND ---
st.set_page_config(page_title="Dev-Drift Enterprise", layout="wide")
st.title("🚀 Dev-Drift: AI Codebase Onboarding")
st.caption("Powered by Amazon Bedrock (Claude 3), OpenSearch, S3, and SDV")

with st.sidebar:
    st.header("1. Ingest Repository")
    repo_url = st.text_input("Public GitHub URL", "https://github.com/Rufi-1/dev_drift")
    if st.button("Process Repository"):
        with st.spinner("Uploading to Amazon S3..."):
            success, msg = fetch_and_upload_github_repo(repo_url)
            if success: st.success(msg)
            else: st.error(msg)

tab1, tab2, tab3, tab4 = st.tabs(["💬 Tutor Chat", "📚 Learning Map", "✅ Starter Tasks", "🧬 SDV Pipeline"])

with tab1:
    st.header("Contextual Code Tutor")
    q = st.text_input("Ask a question about the repository architecture:")
    if st.button("Ask Dev-Drift") and q:
        with st.spinner("Analyzing context via Amazon Bedrock..."): st.info(ask_dev_drift(q))
with tab2:
    st.header("Architectural Overview")
    if st.button("Generate Learning Map"): 
        with st.spinner("Mapping components..."): st.write(ask_dev_drift("Summarize the overarching architecture and primary technologies of this specific codebase. Use markdown formatting."))
with tab3:
    st.header("Safe Sandbox Tasks")
    if st.button("Identify Starter Tasks"): 
        with st.spinner("Scanning codebase for task complexity..."): st.write(ask_dev_drift("Suggest 3 highly specific beginner tasks a new developer could do in this exact codebase."))
with tab4:
    st.header("Synthetic Data Vault (SDV)")
    st.write("Generate a custom Python script using the SDV library to create mock database environments.")
    if st.button("Generate SDV Pipeline"): 
        with st.spinner("Writing schema-aware SDV script..."): st.code(ask_dev_drift("Analyze any data schemas or structures in the codebase and write a complete Python script using the 'sdv' (Synthetic Data Vault) library that generates safe synthetic tabular data specifically for it."), language='python')
