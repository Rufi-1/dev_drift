import streamlit as st
import boto3
import requests
import time

# --- CONFIGURATION ---
# Pulling ALL configuration securely from Streamlit Cloud Secrets!
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
    """Fetches top-level files from a public GitHub repo and uploads them to S3."""
    try:
        # URL PARSING LOGIC:
        clean_url = repo_url.replace("https://github.com/", "").replace("http://github.com/", "").strip("/")
        parts = clean_url.split("/")
        
        if len(parts) < 2:
            return False, "Invalid GitHub URL format. Please use https://github.com/owner/repo"
            
        owner, repo = parts[0], parts[1]
        api_url = f"https://api.github.com/repos/{owner}/{repo}/contents"
        
        response = requests.get(api_url)
        if response.status_code != 200:
            return False, "Could not fetch repository. Is it public?"
            
        files_data = response.json()
        uploaded_count = 0
        
        for file in files_data:
            if file['type'] == 'file' and file['name'].endswith(('.py', '.js', '.ts', '.md', '.txt')):
                file_content = requests.get(file['download_url']).text
                s3_client.put_object(Bucket=S3_BUCKET_NAME, Key=f"{repo}/{file['name']}", Body=file_content)
                uploaded_count += 1
                
        return True, f"Uploaded {uploaded_count} files to Amazon S3."
    except Exception as e:
        return False, f"Error parsing URL or fetching files: {str(e)}"

def sync_knowledge_base():
    """Tells AWS to read the S3 bucket, chunk the files, and update OpenSearch."""
    response = bedrock_agent_client.start_ingestion_job(
        knowledgeBaseId=KNOWLEDGE_BASE_ID,
        dataSourceId=DATA_SOURCE_ID
    )
    return response['ingestionJob']['ingestionJobId']

def ask_dev_drift(query):
    """Uses RAG to query the codebase via Amazon Bedrock."""
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
st.set_page_config(page_title="Dev-Drift", layout="wide")
st.title("🚀 Dev-Drift: AI Codebase Onboarding")

# Sidebar for Ingestion
with st.sidebar:
    st.header("1. Ingest Repository")
    repo_url = st.text_input("Public GitHub URL", placeholder="https://github.com/tiangolo/fastapi")
    
    if st.button("Process Repository"):
        with st.spinner("Fetching repo and uploading to Amazon S3..."):
            success, message = fetch_and_upload_github_repo(repo_url)
            if success:
                st.success(message)
                with st.spinner("Vectorizing code into Amazon OpenSearch (via Bedrock)..."):
                    sync_knowledge_base()
                    time.sleep(15) # Give AWS a moment to process the ingestion
                st.success("✅ Codebase mapped and ready to query!")
            else:
                st.error(message)

# Main Area Tabs
tab1, tab2, tab3 = st.tabs(["💬 Tutor Chat", "📚 Learning Map", "✅ Starter Tasks"])

with tab1:
    st.header("Contextual Code Tutor")
    question = st.text_input("Ask a question about the repository architecture or functions:")
    if st.button("Ask Dev-Drift"):
        if question:
            with st.spinner("Retrieving context from OpenSearch & generating answer..."):
                answer = ask_dev_drift(question)
                st.info(answer)
        else:
            st.warning("Please enter a question.")

with tab2:
    st.header("Architectural Overview")
    if st.button("Generate Learning Map"):
        with st.spinner("Analyzing system architecture..."):
            mapping = ask_dev_drift("Summarize the overall architecture of this codebase and list the main entry points.")
            st.write(mapping)

with tab3:
    st.header("Safe Sandbox Tasks")
    if st.button("Identify Starter Tasks"):
        with st.spinner("Finding beginner-friendly tasks..."):
            tasks = ask_dev_drift("Based on the codebase, suggest 3 beginner-friendly tasks a new developer could do, such as adding missing comments or writing a test.")
            st.write(tasks)
