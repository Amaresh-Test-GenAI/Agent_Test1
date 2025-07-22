import boto3
import time
import uuid
import json
from requests_aws4auth import AWS4Auth
import requests
import time
import uuid
import botocore.exceptions


region = "us-east-1"
collection_name = "test-genai-1"
embedding_model_arn = "arn:aws:bedrock:us-east-1::foundation-model/amazon.titan-embed-text-v1"
s3_bucket_arn = "arn:aws:s3:::genai-test-dg"
s3_prefix = "test-kb/"
agent_name = "Test-Agent_GENAI-3"
# instruction = " You are a helpful assistant that answers questions using the knowledge base For questions about data transformations, respond with the source tables, target tables, and transformation logic in JSON format."


aoss = boto3.client("opensearchserverless", region_name=region)
bedrock = boto3.client("bedrock-agent", region_name=region)
runtime = boto3.client("bedrock-agent-runtime", region_name=region)
sts = boto3.client("sts", region_name=region)
# account_id = sts.get_caller_identity()["Account"]
def ensure_opensearch_policies():
    print("Ensuring OpenSearch Serverless security policies...")

    
    try:
        aoss.create_security_policy(
            name="encryption-policy-genai",
            type="encryption",
            policy=json.dumps({
                "Rules": [{"ResourceType": "collection", "Resource": ["collection/*"]}],
                "AWSOwnedKey": True
            })
        )
        print("Encryption policy created.")
    except aoss.exceptions.ConflictException:
        print("Encryption policy already exists.")

    
    try:
        aoss.create_security_policy(
            name="network-policy-genai",
            type="network",
            policy=json.dumps([{
                "Rules": [{"ResourceType": "collection", "Resource": ["collection/*"]}],
                "AllowFromPublic": True
            }])
        )
        print("Network policy created.")
    except aoss.exceptions.ConflictException:
        print("Network policy already exists.")

    
    policy_name = "data-policy-test-genai-1"
    access_policy_document = [{
        "Rules": [
            {
                "ResourceType": "collection",
                "Resource": ["collection/test-genai-1"],
                "Permission": ["aoss:*"]
            },
            {
                "ResourceType": "index",
                "Resource": ["index/test-genai-1/genai-index"],
                "Permission": ["aoss:*"]
            }
        ],
        "Principal": [
            "arn:aws:iam::406099943223:role/BedrockKBRole",
            "arn:aws:iam::406099943223:role/BedrockKnowledgeBaseAccessRole",
            "arn:aws:iam::406099943223:user/GenAI_Offshore_team_test"
        ]
    }]

    try:
        aoss.create_access_policy(
            name=policy_name,
            type="data",
            policy=json.dumps(access_policy_document)
        )
        print("Data access policy created.")
    except aoss.exceptions.ConflictException:
        print("Data access policy already exists. Updating it...")
        existing = aoss.list_access_policies(type="data", resource=["collection/test-genai-1"])
        current_version = None
        for policy in existing["accessPolicySummaries"]:
            if policy["name"] == policy_name:
                current_version = policy["policyVersion"]
                break
        if current_version:
            try:
                aoss.update_access_policy(
                    name=policy_name,
                    type="data",
                    policy=json.dumps(access_policy_document),
                    policyVersion=current_version
                )
                print("Data access policy updated.")
            except aoss.exceptions.ValidationException as e:
                if "No changes detected" in str(e):
                    print("No changes to update in data access policy.")
                else:
                    raise
        else:
            print("Couldn't find existing policy to update.")

def create_collection(name):
    print(f"Creating OpenSearch collection: {name}")
    try:
        aoss.create_collection(name=name, type="VECTORSEARCH")
    except aoss.exceptions.ConflictException:
        print("Collection already exists.")

    while True:
        resp = aoss.list_collections()
        for col in resp["collectionSummaries"]:
            if col["name"] == name and col["status"] == "ACTIVE":
                print("Collection is ACTIVE")
                collection_arn = col["arn"]
                break
        else:
            print("Waiting for collection to become ACTIVE...")
            time.sleep(10)
            continue
        break
    create_vector_index(name, "genai-index")
    return collection_arn

def create_vector_index(collection_name, index_name):
    print(f"Creating vector index: {index_name}")
    collections = aoss.list_collections()["collectionSummaries"]
    collection_arn = next((col["arn"] for col in collections if col["name"] == collection_name), None)
    if not collection_arn:
        raise Exception(f"Collection ARN not found for {collection_name}")
    try:
        parts = collection_arn.split(":")
        region = parts[3]
        endpoint_name = collection_arn.split("/")[-1]
        endpoint = f"{endpoint_name}.{region}.aoss.amazonaws.com"
    except Exception as e:
        raise Exception(f"Failed to parse endpoint from ARN: {e}")

    url = f"https://{endpoint}/{index_name}"
    headers = {"Content-Type": "application/json"}

    index_config = {
        "settings": {
            "index": {
                "knn": True,
                "knn.algo_param.ef_search": 512
            }
        },
        "mappings": {
            "properties": {
                "vector": {
                    "type": "knn_vector",
                    "dimension": 1536,
                    "method": {
                        "name": "hnsw",
                        "space_type": "l2",  
                        "engine": "faiss",
                        "parameters": {
                            "ef_construction": 512,
                            "m": 16
                        }
                    }
                },
                "text": {"type": "text"},
                "metadata": {"type": "keyword"}
            }
        }
    }

    try:
        session = boto3.Session()
        credentials = session.get_credentials().get_frozen_credentials()
        aws_auth = AWS4Auth(
            credentials.access_key,
            credentials.secret_key,
            region,
            "aoss",
            session_token=credentials.token
        )
        response = requests.put(url, headers=headers, auth=aws_auth, data=json.dumps(index_config))
        if response.status_code == 200:
            print("Vector index created.")
        elif response.status_code == 400 and 'resource_already_exists_exception' in response.text:
            print("Vector index already exists.")
        else:
            raise Exception(f"Failed to create vector index: {response.text}")
    except Exception as e:
        print(f"Exception during vector index creation: {e}")

def create_knowledge_base(collection_arn):
    print("Creating Knowledge Base...")
    index_name = "genai-index"
    response = bedrock.create_knowledge_base(
        name=f"kb-{uuid.uuid4().hex[:6]}",
        roleArn="arn:aws:iam::406099943223:role/BedrockKBRole",
        description="Auto-created KB",
        knowledgeBaseConfiguration={
            "type": "VECTOR",
            "vectorKnowledgeBaseConfiguration": {
                "embeddingModelArn": embedding_model_arn
            }
        },
        storageConfiguration={
            "type": "OPENSEARCH_SERVERLESS",
            "opensearchServerlessConfiguration": {
                "collectionArn": collection_arn,
                "vectorIndexName": index_name,
                "fieldMapping": {
                    "vectorField": "vector",
                    "textField": "text",
                    "metadataField": "metadata"
                }
            }
        }
    )
    kb_id = response["knowledgeBase"]["knowledgeBaseId"]
    print("Knowledge Base created:", kb_id)
    return kb_id

def wait_for_kb_active(kb_id):
    print("Waiting for Knowledge Base to become ACTIVE...")
    while True:
        response = bedrock.get_knowledge_base(knowledgeBaseId=kb_id)
        status = response["knowledgeBase"]["status"]
        print(f"KB status: {status}")
        if status == "ACTIVE":
            print("Knowledge Base is ACTIVE")
            break
        elif status == "FAILED":
            raise Exception("Knowledge Base creation FAILED.")
        time.sleep(5)

def create_data_source(kb_id):
    print("Adding S3 data source...")
    response = bedrock.create_data_source(
        knowledgeBaseId=kb_id,
        name="s3-data",
        dataSourceConfiguration={
            "type": "S3",
            "s3Configuration": {
                "bucketArn": s3_bucket_arn,
                "inclusionPrefixes": [s3_prefix]
            }
        },
        vectorIngestionConfiguration={
            "chunkingConfiguration": {
                "chunkingStrategy": "FIXED_SIZE",
                "fixedSizeChunkingConfiguration": {
                    "maxTokens": 512,
                    "overlapPercentage": 20
                }
            }
        }
    )
    data_source_id = response["dataSource"]["dataSourceId"]
    print("Data source added:", data_source_id)
    return data_source_id
def start_ingestion(kb_id, data_source_id):
    print(" Starting ingestion...")
    response = bedrock.start_ingestion_job(
        knowledgeBaseId=kb_id,
        dataSourceId=data_source_id
    )
    job_id = response["ingestionJob"]["ingestionJobId"]
    print(" Ingestion job started:", job_id)

    while True:
        status = bedrock.get_ingestion_job(
            knowledgeBaseId=kb_id,
            dataSourceId=data_source_id,
            ingestionJobId=job_id
        )
        state = status["ingestionJob"]["status"]
        print(" Ingestion status:", state)
        if state in ["COMPLETE", "FAILED"]:
            break
        time.sleep(10)

    if state == "COMPLETE":
        print(" Ingestion complete.")
        print(" Checking for failure reasons (if any):")
        print(status["ingestionJob"].get("failureReasons", []))
        
        
        print(" Retrieving a few chunks from the knowledge base...")
        runtime = boto3.client("bedrock-agent-runtime", region_name="us-east-1")

        try:
            retrieve_response = runtime.retrieve(
                knowledgeBaseId=kb_id,
                retrievalQuery={"text": "What is this document about?"}
            )
            chunks = retrieve_response.get("retrievalResults", [])
            print(f" Retrieved {len(chunks)} chunks.\n")

            for i, chunk in enumerate(chunks[:5], 1):  
                text = chunk.get("content", {}).get("text", "")[:300]
                metadata = chunk.get("content", {}).get("metadata", {})
                print(f" Chunk {i}:")
                print(f"   Text: {text.strip()}")
                print(f"   Metadata: {json.dumps(metadata, indent=2)}\n")
        except Exception as e:
            print("Error while retrieving chunks:", str(e))

    else:
        print("Ingestion failed.")
        print("Failure reasons:")
        print(status["ingestionJob"].get("failureReasons", []))
        raise Exception("Ingestion failed.")


def enable_code_interpreter(agent_id):
    print("Enabling Code Interpreter and User Input action groups...")
    action_group_client = boto3.client("bedrock-agent", region_name="us-east-1")

    def create_action_group(signature, name):
        try:
            response = action_group_client.create_agent_action_group(
                actionGroupName=name,
                actionGroupState="ENABLED",
                agentId=agent_id,
                agentVersion="DRAFT",
                parentActionGroupSignature=signature
            )
            return response["agentActionGroup"]["actionGroupId"]
        except botocore.exceptions.ClientError as e:
            if "ConflictException" in str(e):
                print(f"Action group '{name}' already exists.")
                return None
            else:
                raise e

    user_input_id = create_action_group("AMAZON.UserInput", "UserInputAction")
    code_interp_id = create_action_group("AMAZON.CodeInterpreter", "CodeInterpreterAction")

    
    for ag_id, label in [(user_input_id, "UserInput"), (code_interp_id, "CodeInterpreter")]:
        if ag_id is None:
            continue
        status = ""
        print(f" Waiting for {label} action group to be ENABLED...")
        while status != "ENABLED":
            response = action_group_client.get_agent_action_group(
                agentId=agent_id,
                agentVersion="DRAFT",
                actionGroupId=ag_id
            )
            status = response["agentActionGroup"]["actionGroupState"]
            print(f"{label} status: {status}")
            time.sleep(2)

    print("Action groups ready. Preparing agent again...")
    bedrock.prepare_agent(agentId=agent_id)
    wait_for_agent_status(bedrock, agent_id, "PREPARED")
    print("Agent re-prepared with action groups.")


import boto3
import time

bedrock = boto3.client("bedrock-agent")
print("create_agent_version" in dir(bedrock))  

bedrock_runtime = boto3.client("bedrock-agent-runtime")
import boto3
import time
import json

bedrock = boto3.client("bedrock-agent")

def create_agent(kb_id):
    print("Creating agent...")
    role_arn = "arn:aws:iam::406099943223:role/BedrockKBRole"
 
    base_prompt_template = json.dumps(
    "<|begin_of_text|><|header_start|>user<|header_end|> "
    "You are an intelligent ETL Analyst. Your task is to analyze a SQL stored procedure and extract all column-level transformations involved in populating the source to target table. "
    "Given a SQL stored procedure and data model metadata (including source tables, source schema, source data model, and target table), you must identify SELECT, INSERT, UPDATE, and JOIN operations relevant to those tables. "
    "For each field in the target table, determine the source field(s), the transformation logic, and the transformation type (Direct Mapping, Expression, Lookup, or No Transformation). "
    "Output a JSON array with sourceDataModel, sourceSchema, sourceTable, sourceFieldName, transformationLogic, transformationType, and targetFieldName. "
    "If multiple source fields are used, list them comma-separated. "
    "If a field is hardcoded (e.g., CURRENT_TIMESTAMP()), use transformationType as 'Expression'. "
    "If no mapping exists, set all source fields to 'No Mapping', transformationLogic to 'No Mapping', and transformationType to 'No Transformation'. "
    "\\n\\n**Here is the SQL and metadata input:**\\n{{input}}<|eot|>"
)
    print(">>>>>>>>>> DEBUG BaseTemplate:>>>>>>>>>>> ", base_prompt_template)
 
    response = bedrock.create_agent(
        agentName="genai-agent",
        agentResourceRoleArn=role_arn,
        # instruction=base_prompt_template["messages"][0]["content"],
        instruction="You are a helpful assistant that answers questions using the knowledge base For questions about data transformations, respond with the source tables, target tables, and transformation logic in JSON format.",
        description="ETL Analyst Agent for parsing SQL stored procedures",
        foundationModel="arn:aws:bedrock:us-east-1:406099943223:inference-profile/us.meta.llama4-maverick-17b-instruct-v1:0",
        idleSessionTTLInSeconds=600,
        orchestrationType="DEFAULT",
        memoryConfiguration={
            "enabledMemoryTypes": ["SESSION_SUMMARY"],
            "sessionSummaryConfiguration": {"maxRecentSessions": 3},
            "storageDays": 1
        },
        promptOverrideConfiguration={
            "promptConfigurations": [
                {
                    "promptType": "ORCHESTRATION",
                    "promptCreationMode": "OVERRIDDEN",
                    "promptState": "ENABLED",
                    "basePromptTemplate": base_prompt_template,
                    "parserMode": "DEFAULT",
                    "inferenceConfiguration": {
                        "maximumLength": 4000,
                        "temperature": 0.5,
                        "topP": 0.9,
                        "topK": 250,
                        "stopSequences": []
                    }
                }
            ]
        }
    )
 
    agent_id = response["agent"]["agentId"]
    print(f"Agent created: {agent_id}")
    wait_for_agent_status(bedrock, agent_id, "NOT_PREPARED")
 
    print("Preparing agent...")
    bedrock.prepare_agent(agentId=agent_id)
    wait_for_agent_status(bedrock, agent_id, "PREPARED")
    print("Agent prepared.")
 
    print("Attaching Knowledge Base...")
    attach_response = bedrock.associate_agent_knowledge_base(
        agentId=agent_id,
        agentVersion="DRAFT",
        knowledgeBaseId=kb_id,
        knowledgeBaseState="ENABLED",
        description="Attach KB to agent"
    )
    print(f"KB attached: {attach_response}")
 
    print("Re-preparing agent after KB attachment...")
    bedrock.prepare_agent(agentId=agent_id)
    wait_for_agent_status(bedrock, agent_id, "PREPARED")
    print("Agent re-prepared.")
 
    print("Creating alias 'prod' (auto-version)...")
    alias_response = bedrock.create_agent_alias(
        agentId=agent_id,
        agentAliasName='prod'
    )
    alias_id = alias_response['agentAlias']['agentAliasId']
    print(f"Alias created: {alias_id}")
    return agent_id, alias_id

# def create_agent(kb_id):
#     print("Creating agent...")
#     role_arn = "arn:aws:iam::406099943223:role/BedrockKBRole"
#     instruction = """
# You are an intelligent ETL Analyst. Your task is to analyze a SQL stored procedures and extract all column-level transformations involved in populating the source to target table.
 
# Given:
# - A SQL Stored Procedure
# - Below is the Data Model Metadata specifying source tables, source schema, source data model, and the target table:
#  **Data model metadata**, [
#            {
#              "sourceDataModel": "Datamodel_SOURCE_ISU Training _PA_TABLES",
#              "dataSourceType": "Snowflake",
#              "sourceSchema": "TESTDB.DG",
#              "sourceTables": [
#                "MISC_ISU_PA_CPNT_COMPLIANCE_DATA",
#                "MISC_ISU_PA_CBT_STUD_CPNT_MOD",
#                "MISC_ISU_PA_STUD_CPNT",
#                "MISC_ISU_PA_CPNT",
#                "MISC_ISU_PA_CMPL_STAT",
#                "MISC_ISU_PA_ENROLL_SEAT",
#                "MISC_ISU_PA_QUAL",
#                "MISC_ISU_PA_CPNT_EVTHST",
#                "MISC_ISU_PA_STUD_QUAL_CPNT",
#                "MISC_ISU_PA_CBT_STUD_CPNT"
#              ],
#              "targetTable": "EDW_STAGE_ISUTRAINING"
#            }
#          ]
 
# Your goal is to:
# 1. Parse the stored procedure and identify all SELECT, INSERT, UPDATE, and JOIN operations relevant to the specified source and target tables.
# 2. For each field in the target table, determine:
#    - The source field(s) it comes from
#    - The transformation logic applied (if any)
#    - The type of transformation: "Direct Mapping", "Expression", "Lookup", or "No Transformation"
# 3. Output a JSON array containing transformation details for each field.
 
# The output must strictly follow this format:
# ```json
# [
#   {
#     "sourceDataModel": "string",
#     "sourceSchema": "string",
#     "sourceTable": "string",
#     "sourceFieldName": "string",
#     "transformationLogic": "string",
#     "transformationType": "Direct Mapping | Expression | Lookup | No Transformation",
#     "targetFieldName": "string"
#   }
# ]
# Rules:
#     - Source field name whould be column name from source table, dont add alias names or transformation logic in sourceFieldName.
#     - If we have multiple columns involved from source tables, add multiple columns with comma seperator in sourceFieldName.
#     - For each target column name get the valid transformationLogic and transformationType from the given source tables.
#   - Only include fields used in the final transformation to the target table.
#   - If a field is derived via expressions (e.g., concatenation, CASE statements, calculations), mark transformationType as "Expression" and provide the full expression in transformationLogic.
#   - If a field is retrieved via a lookup/join to another table not listed in the provided sources, mark transformationType as "Lookup".
#   - If a field is directly mapped without any manipulation, mark transformationType as "Direct Mapping" and set transformationLogic to "DIRECT".
#   - If a field is hardcoded or defaulted (e.g., CURRENT_TIMESTAMP()), mark transformationType as "Expression" and specify the value in transformationLogic.
 
# 🚫 *** Important Rule for Unmapped source to target Columns**:
 
# -   If no source column, table, or transformation logic is found for a target column, then:
# -   Set "transformationLogic": "No Mapping"
# -   And for "sourceDataModel", "sourceSchema", "sourceTable", and "sourceFieldName", set them to "No Mapping" as well.
# -   Use "transformationType": "No Transformation"
# """
#     response = bedrock.create_agent(
#         agentName="genai-agent",
#         # foundationModel="anthropic.claude-3-haiku-20240307-v1:0",
#         foundationModel="anthropic.claude-3-5-sonnet-20240620-v1:0",
#         # foundationModel="arn:aws:bedrock:us-east-1:406099943223:inference-profile/us.anthropic.claude-3-5-haiku-20241022-v1:0",
#         # foundationModel="arn:aws:bedrock:us-east-1::foundation-model/anthropic.claude-3-5-haiku-20241022-v1:0",
#         instruction=instruction,
#         agentResourceRoleArn=role_arn,
#         idleSessionTTLInSeconds=600,
#         memoryConfiguration={ 
#         "enabledMemoryTypes": ["SESSION_SUMMARY"],
#         "sessionSummaryConfiguration": {
#         "maxRecentSessions": 3
#         },
#         "storageDays": 1
#         }
#     )
#     agent_id = response["agent"]["agentId"]
#     print(f"Agent created: {agent_id}")

    
#     wait_for_agent_status(bedrock, agent_id, "NOT_PREPARED")

    
#     print("Preparing agent...")
#     bedrock.prepare_agent(agentId=agent_id)
#     wait_for_agent_status(bedrock, agent_id, "PREPARED")
#     print("Agent prepared.")

    
#     print(" Attaching Knowledge Base...")
#     attach_response = bedrock.associate_agent_knowledge_base(
#         agentId=agent_id,
#         agentVersion="DRAFT",
#         knowledgeBaseId=kb_id,
#         knowledgeBaseState="ENABLED",  
#         description="Attach KB to agent"
#     )
#     print(f" KB attached: {attach_response}")

    
#     print("Re-preparing agent after KB attachment...")
#     bedrock.prepare_agent(agentId=agent_id)
#     wait_for_agent_status(bedrock, agent_id, "PREPARED")
#     print("Agent re-prepared.")

    
#     print("Creating alias 'prod' (auto-version)...")
#     alias_response = bedrock.create_agent_alias(
#         agentId=agent_id,
#         agentAliasName='prod'
#     )
#     alias_id = alias_response['agentAlias']['agentAliasId']
#     print(f"Alias created: {alias_id}")

#     return agent_id, alias_id

def wait_for_index_ready(collection_arn, index_name, timeout=120, interval=5):
    print(f" Waiting for index '{index_name}' to become available...")

    parts = collection_arn.split(":")
    region = parts[3]
    endpoint_name = collection_arn.split("/")[-1]
    endpoint = f"{endpoint_name}.{region}.aoss.amazonaws.com"

    url = f"https://{endpoint}/_cat/indices/{index_name}?format=json"
    session = boto3.Session()
    credentials = session.get_credentials().get_frozen_credentials()
    aws_auth = AWS4Auth(
        credentials.access_key,
        credentials.secret_key,
        region,
        "aoss",
        session_token=credentials.token
    )

    start_time = time.time()
    while time.time() - start_time < timeout:
        response = requests.get(url, auth=aws_auth)
        if response.status_code == 200:
            try:
                index_info = response.json()
                if any(idx.get("index") == index_name for idx in index_info):
                    print(" Index is now available.")
                    return
            except Exception:
                pass
        print(f" Index not ready (status {response.status_code}). Retrying...")
        time.sleep(interval)

    raise TimeoutError(f" Index '{index_name}' did not become available within {timeout} seconds.")




def wait_for_alias_ready(agent_id, alias_id, timeout=600):
    print("Waiting for agent alias to become READY or PREPARED...")
    start_time = time.time()
    while True:
        response = bedrock.get_agent_alias(agentId=agent_id, agentAliasId=alias_id)
        status = response["agentAlias"]["agentAliasStatus"]
        print(f"Alias status: {status}")
        if status in ["READY", "PREPARED"]:  
            print(f"Agent alias is {status}.")
            break
        elif status == "FAILED":
            raise Exception("Alias creation failed.")
        elif time.time() - start_time > timeout:
            raise TimeoutError("Timeout waiting for alias to become READY.")
        time.sleep(5)

import time


def wait_for_agent_status(bedrock_client, agent_id, expected_status, max_retries=60, interval=5):
    print(f"Waiting for agent {agent_id} to reach status: {expected_status}")
    
    for attempt in range(max_retries):
        try:
            response = bedrock_client.get_agent(agentId=agent_id)
            current_status = response.get("agent", {}).get("agentStatus", "UNKNOWN")
        except Exception as e:
            current_status = "UNKNOWN"

        print(f"Agent status: {current_status}")

        if current_status == expected_status:
            print(f"Agent reached status: {expected_status}")
            return
        elif current_status in ["FAILED", "DELETING", "DELETED"]:
            raise Exception(f"Agent reached terminal state: {current_status}")
        
        time.sleep(interval)

    raise TimeoutError(f"Agent did not reach '{expected_status}' status within {max_retries * interval} seconds.")


def attach_kb_to_agent(agent_id, kb_id):
    print("Linking Knowledge Base to Agent...")

    bedrock.associate_agent_knowledge_base(
        agentId=agent_id,
        agentVersion="DRAFT",  
        knowledgeBaseId=kb_id,
        knowledgeBaseState="ENABLED",
        description="Linking KB to agent"
    )

    print("Knowledge base successfully linked.")

# def invoke_agent(agent_id, alias_id, question):
#     print(f"Asking agent: {question}")
#     session_id = str(uuid.uuid4())

#     response_stream = runtime.invoke_agent(
#         agentId=agent_id,
#         agentAliasId=alias_id,
#         sessionId=session_id,
#         inputText=question
#     )

#     print("Agent response:")
#     full_response = ""
#     for event in response_stream:
#         if "chunk" in event and "bytes" in event["chunk"]:
#             chunk_data = event["chunk"]["bytes"].decode("utf-8")
#             print(chunk_data, end="")  
#             full_response += chunk_data

#     print("Done streaming agent response.")
#     return full_response

def invoke_agent(agent_id, alias_id, question):
    import uuid
    import boto3
    import json
    import botocore.exceptions
 
    print(f"Asking agent: {question}")
    session_id = str(uuid.uuid4())
    runtime = boto3.client("bedrock-agent-runtime", region_name="us-east-1")
 
    try:
        response = runtime.invoke_agent(
            agentId=agent_id,
            agentAliasId=alias_id,
            sessionId=session_id,
            inputText=question
        )
 
        print("Raw response:", response)
 
        # Handle streaming response
        if "completion" in response:
            full_response = ""
            for event in response["completion"]:
                chunk_bytes = event.get("chunk", {}).get("bytes")
                if chunk_bytes:
                    try:
                        full_response += chunk_bytes.decode("utf-8", errors="replace")
                    except Exception as decode_err:
                        print(f"⚠️ Error decoding chunk: {decode_err}")
            print("\nAgent Response:\n")
            print(full_response.strip())
            return full_response.strip()
 
        # Handle non-streaming fallback
        elif "completionResponse" in response:
            output = response["completionResponse"].get("text", "")
            print("\nAgent Response:\n")
            print(output.strip())
            return output.strip()
 
        else:
            print("⚠️ Unexpected response structure:")
            print(json.dumps(response, indent=2))
            return ""
 
    except botocore.exceptions.EventStreamError as e:
        print("❌ Stream error:", str(e))
        if hasattr(e, "error_response"):
            print("Error details:")
            print(json.dumps(e.error_response, indent=2))
        return ""
 
    except Exception as e:
        print("❌ General error:", str(e))
        return ""


if __name__ == "__main__":
    ensure_opensearch_policies()
    collection_arn = create_collection(collection_name)
    wait_for_index_ready(collection_arn, "genai-index")  
    time.sleep(30)
    kb_id = create_knowledge_base(collection_arn)
    wait_for_kb_active(kb_id)
    data_source_id = create_data_source(kb_id)
    start_ingestion(kb_id, data_source_id)
    agent_id, alias_id = create_agent(kb_id)
    enable_code_interpreter(agent_id)
    wait_for_alias_ready(agent_id, alias_id)
    invoke_agent(agent_id, alias_id, "List the etl mappings for the target coloumn")



