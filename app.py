import streamlit as st
import boto3
import requests
import time
from botocore.exceptions import ClientError

# --- CONFIGURATION ---
AWS_REGION = st.secrets["AWS_REGION"]
AWS_ACCESS_KEY = st.secrets["AWS_ACCESS_KEY"]
AWS_SECRET_KEY = st.secrets["AWS_SECRET_KEY"]
S3_BUCKET_NAME = st.secrets["S3_BUCKET_NAME"]
KNOWLEDGE_BASE_ID = st.secrets["KNOWLEDGE_BASE_ID"]
DATA_SOURCE_ID = st.secrets["DATA_SOURCE_ID"]

# Initialize AWS Clients
s3_client = boto3.client('s3', region_name=AWS_REGION, aws_access_key_id=AWS_ACCESS_KEY, aws_secret_access_key=AWS_SECRET_KEY)
bedrock_agent_client = boto3.client('bedrock-agent', region_name=AWS_REGION, aws_access_key_id=AWS_ACCESS_KEY, aws_secret_access_key=AWS_SECRET_KEY)
bedrock_agent_runtime = boto3.client('bedrock-agent-runtime', region_name=AWS_REGION, aws_access_key_id=AWS_ACCESS_KEY, aws_secret_access_key=AWS_SECRET_KEY)

# --- HELPER FUNCTIONS ---
def fetch_and_upload_github_repo(repo_url):
    """Fetches full code files. No truncation. Uncompromised payload."""
    try:
        clean_url = repo_url.replace("https://github.com/", "").replace("http://github.com/", "").strip("/")
        parts = clean_url.split("/")
        
        if len(parts) < 2:
            return False, "Invalid GitHub URL format."
            
        owner, repo = parts[0], parts[1]
        api_url = f"https://api.github.com/repos/{owner}/{repo}/contents"
        
        response = requests.get(api_url)
        if response.status_code != 200:
            return False, "Could not fetch repository. Is it public?"
            
        files_data = response.json()
        uploaded_count = 0
        
        # Filter for valid code/text files only to avoid uploading binaries/images
        valid_extensions = ('.py', '.js', '.ts', '.jsx', '.tsx', '.md', '.txt', '.json', '.yml', '.yaml', '.html', '.css')
        
        for file in files_data:
            if file['type'] == 'file' and file['name'].lower().endswith(valid_extensions):
                file_content = requests.get(file['download_url']).text
                
                # Full file upload - no truncation
                s3_client.put_object(Bucket=S3_BUCKET_NAME, Key=f"{repo}/{file['name']}", Body=file_content)
                uploaded_count += 1
                
        return True, f"Successfully ingested {uploaded_count} raw repository files."
    except Exception as e:
        return False, f"Error parsing URL: {str(e)}"

def sync_knowledge_base_with_retry(max_retries=5):
    """Enterprise rate-limit handling using Exponential Backoff."""
    retries = 0
    backoff_time = 5 # Start with a 5 second wait
    
    while retries < max_retries:
        try:
            response = bedrock_agent_client.start_ingestion_job(
                knowledgeBaseId=KNOWLEDGE_BASE_ID,
                dataSourceId=DATA_SOURCE_ID
            )
            return True, response['ingestionJob']['ingestionJobId']
        
        except ClientError as e:
            if e.response['Error']['Code'] == 'TooManyRequestsException' or e.response['Error']['Code'] == 'ThrottlingException':
                st.toast(f"AWS Rate Limit hit. Retrying in {backoff_time} seconds... (Attempt {retries + 1}/{max_retries})")
                time.sleep(backoff_time)
                retries += 1
                backoff_time *= 2 # Double the wait time (Exponential Backoff)
            else:
                return False, f"AWS Error: {str(e)}"
                
    return False, "Failed to sync after maximum retries. The repository is too large for the current AWS quota."

def ask_dev_drift(query):
    """Uses RAG to query the codebase via Amazon Bedrock Claude 3."""
    response = bedrock_agent_runtime.retrieve_and_generate(
        input={'text': query},
        retrieveAndGenerateConfiguration={
            'type': 'KNOWLEDGE_BASE',
            'knowledgeBaseConfiguration': {
                'knowledgeBaseId': KNOWLEDGE_BASE_ID,
                'modelArn': f'arn:aws:bedrock:{AWS_REGION}::foundation-model/anthropic.claude-3-haiku-20240307-v1:0'
            }
        }
    )
    return response['output']['text']

# --- UI FRONTEND ---
st.set_page_config(page_title="Dev-Drift Enterprise", layout="wide")
st.title("🚀 Dev-Drift: AI Codebase Onboarding")
st.caption("Powered by Amazon Bedrock, OpenSearch Serverless, and SDV")

# Sidebar for Ingestion
with st.sidebar:
    st.header("1. Ingest Repository")
    repo_url = st.text_input("Public GitHub URL", placeholder="https://github.com/tiangolo/fastapi")
    
    if st.button("Process Repository"):
        with st.spinner("Fetching full repository into Amazon S3..."):
            success, message = fetch_and_upload_github_repo(repo_url)
            if success:
                st.success(message)
                with st.spinner("Vectorizing code into OpenSearch (Handling API Quotas)..."):
                    sync_success, sync_message = sync_knowledge_base_with_retry()
                    if sync_success:
                        time.sleep(15) 
                        st.success("✅ Codebase mapped and ready to query!")
                    else:
                        st.error(sync_message)
            else:
                st.error(message)

# Main Area Tabs
tab1, tab2, tab3, tab4 = st.tabs(["💬 Tutor Chat", "📚 Learning Map", "✅ Starter Tasks", "🧬 SDV Synthetic Data"])

with tab1:
    st.header("Contextual Code Tutor")
    question = st.text_input("Ask a question about the repository architecture or functions:")
    if st.button("Ask Dev-Drift"):
        if question:
            with st.spinner("Retrieving context from OpenSearch..."):
                st.info(ask_dev_drift(question))

with tab2:
    st.header("Architectural Overview")
    if st.button("Generate Learning Map"):
        with st.spinner("Analyzing system architecture..."):
            st.write(ask_dev_drift("Summarize the overall architecture of this codebase and list the main entry points."))

with tab3:
    st.header("Safe Sandbox Tasks")
    if st.button("Identify Starter Tasks"):
        with st.spinner("Finding beginner-friendly tasks..."):
            st.write(ask_dev_drift("Based on the codebase, suggest 3 beginner-friendly tasks a new developer could do, such as adding missing comments or writing a test."))

with tab4:
    st.header("Synthetic Data Vault (SDV) Generation")
    st.write("Generate a custom Python script using the SDV library to create mock database environments based on this specific repository's schemas.")
    if st.button("Generate SDV Pipeline"):
        with st.spinner("Analyzing codebase schemas for SDV modeling..."):
            sdv_prompt = "Analyze the codebase for any data models, schemas, or database structures. Write a complete Python script using the 'sdv' (Synthetic Data Vault) library that generates realistic, safe synthetic tabular data tailored to these specific schemas so developers can test without production data."
            st.code(ask_dev_drift(sdv_prompt), language='python')
