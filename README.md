# AWS Bedrock Knowledge Base Deletion Scripts

This repository contains scripts to delete all AWS Bedrock Knowledge Bases in your account. These scripts are particularly useful when you have many Knowledge Bases that are failing to delete through the AWS Console due to vector store configuration issues.

## Problem Solved

If you're experiencing errors like:
```
Failed to delete Knowledge Base - XJJGTNWXFW
Unable to delete data from vector store for data source with ID HIOKMAMIBW. 
Check your vector store configurations and permissions and retry your request. 
If the issue persists, consider updating the dataDeletionPolicy of the data source to RETAIN and retry your request.
```

These scripts will automatically handle such issues by:
1. Updating data source deletion policies to `RETAIN` when vector store deletion fails
2. Retrying deletions with proper error handling
3. Processing all Knowledge Bases in your account systematically

## Available Scripts

### 1. Python Script (`delete_bedrock_kbs.py`)
- **Recommended**: More robust error handling and detailed output
- Requires Python 3.6+ and boto3

### 2. Bash Script (`delete_bedrock_kbs.sh`)
- Lightweight alternative using AWS CLI
- Requires AWS CLI and jq

## Prerequisites

### For Python Script:
```bash
# Install Python dependencies
pip install -r requirements.txt

# Or install manually
pip install boto3
```

### For Bash Script:
```bash
# Install AWS CLI (if not already installed)
curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
unzip awscliv2.zip
sudo ./aws/install

# Install jq (JSON processor)
sudo apt-get install jq  # Ubuntu/Debian
# or
sudo yum install jq      # CentOS/RHEL
# or
brew install jq          # macOS
```

### AWS Configuration:
```bash
# Configure AWS credentials
aws configure
# or set environment variables
export AWS_ACCESS_KEY_ID=your_access_key
export AWS_SECRET_ACCESS_KEY=your_secret_key
export AWS_DEFAULT_REGION=us-east-1
```

## Usage

### Python Script Examples:

```bash
# List all Knowledge Bases without deleting (dry run)
./delete_bedrock_kbs.py --dry-run

# List KBs in a specific region
./delete_bedrock_kbs.py --dry-run --region us-west-2

# Delete all KBs with confirmation prompt
./delete_bedrock_kbs.py

# Delete all KBs without confirmation (be careful!)
./delete_bedrock_kbs.py --confirm

# Delete KBs in a specific region
./delete_bedrock_kbs.py --region eu-west-1

# Show available regions
./delete_bedrock_kbs.py --list-regions
```

### Bash Script Examples:

```bash
# List all Knowledge Bases without deleting (dry run)
./delete_bedrock_kbs.sh --dry-run

# Delete all KBs with confirmation prompt
./delete_bedrock_kbs.sh

# Delete all KBs without confirmation
./delete_bedrock_kbs.sh --confirm

# Delete KBs in a specific region
./delete_bedrock_kbs.sh --region us-west-2

# Show help
./delete_bedrock_kbs.sh --help
```

## How It Works

Both scripts follow the same process:

1. **List Knowledge Bases**: Discovers all KBs in the specified region
2. **Process Data Sources**: For each KB, identifies and deletes associated data sources
3. **Handle Vector Store Errors**: If deletion fails due to vector store issues:
   - Updates the data source deletion policy to `RETAIN`
   - Retries the deletion operation
4. **Delete Knowledge Base**: Removes the KB itself after data sources are cleaned up
5. **Retry Logic**: Multiple attempts with exponential backoff for failed operations

## Error Handling

The scripts handle common issues:

- **Vector Store Configuration Errors**: Automatically updates deletion policies
- **Permission Issues**: Provides clear error messages and suggestions
- **Rate Limiting**: Includes delays between operations
- **Network Timeouts**: Implements retry logic with backoff

## Sample Output

```
🤖 AWS Bedrock Knowledge Base Cleaner
==================================================
🔍 Listing Knowledge Bases in region us-east-1...
📊 Found 36 Knowledge Bases
  1. My Test KB (ID: XJJGTNWXFW) - Status: ACTIVE
  2. Another KB (ID: YKKGTNWXGW) - Status: ACTIVE
  ...

⚠️  WARNING: This will delete ALL 36 Knowledge Bases!
This action cannot be undone.
Are you sure you want to continue? (type 'DELETE' to confirm): DELETE

🚀 Starting deletion of 36 Knowledge Bases...

[1/36] Processing: My Test KB
🗑️  Deleting Knowledge Base: My Test KB (ID: XJJGTNWXFW)
  📁 Found 1 data sources to delete first
    🗑️  Deleting data source: test-data-source (ID: HIOKMAMIBW)
    ⚠️  Vector store error on attempt 1, updating deletion policy...
    ✅ Updated data source HIOKMAMIBW deletion policy to RETAIN
    ✅ Deleted data source HIOKMAMIBW
    ⏳ Waiting for data source deletions to complete...
✅ Successfully deleted Knowledge Base: My Test KB

...

📊 Deletion Summary:
  ✅ Successful: 35
  ❌ Failed: 1
```

## Troubleshooting

### Common Issues:

1. **Credentials Error**:
   ```
   ❌ AWS credentials not found
   ```
   **Solution**: Run `aws configure` or set environment variables

2. **Permission Denied**:
   ```
   ❌ Failed to list knowledge bases. Check your permissions
   ```
   **Solution**: Ensure your AWS user/role has Bedrock permissions:
   - `bedrock:ListKnowledgeBases`
   - `bedrock:DeleteKnowledgeBase`
   - `bedrock:ListDataSources`
   - `bedrock:DeleteDataSource`
   - `bedrock:UpdateDataSource`

3. **Region Issues**:
   ```
   ❌ Failed to list knowledge bases
   ```
   **Solution**: Bedrock is not available in all regions. Try:
   - `us-east-1`
   - `us-west-2`
   - `eu-west-1`

4. **Vector Store Permissions**:
   If deletions continue to fail after policy updates, you may need to manually clean up vector store resources (OpenSearch clusters, Pinecone indexes, etc.) in your AWS account.

## Required IAM Permissions

```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "bedrock:ListKnowledgeBases",
                "bedrock:DeleteKnowledgeBase",
                "bedrock:GetKnowledgeBase",
                "bedrock:ListDataSources",
                "bedrock:DeleteDataSource",
                "bedrock:GetDataSource",
                "bedrock:UpdateDataSource"
            ],
            "Resource": "*"
        }
    ]
}
```

## Safety Features

- **Dry Run Mode**: Test the script without making changes
- **Confirmation Prompt**: Requires typing "DELETE" to proceed
- **Progress Tracking**: Shows detailed progress for each operation
- **Error Recovery**: Continues processing even if some deletions fail
- **Summary Report**: Provides final count of successes and failures

## Support

If you continue to experience issues after running these scripts:

1. Check AWS CloudTrail logs for detailed error information
2. Verify vector store resources (OpenSearch, Pinecone) in your account
3. Contact AWS Support for assistance with persistent vector store issues

---

**⚠️ Warning**: These scripts will delete ALL Knowledge Bases in the specified region. This action cannot be undone. Always test with `--dry-run` first!