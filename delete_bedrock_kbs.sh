#!/bin/bash

# AWS Bedrock Knowledge Base Deletion Script (Bash version)
# This script deletes all AWS Bedrock Knowledge Bases using AWS CLI

set -e

# Default values
REGION="us-east-1"
DRY_RUN=false
CONFIRM=false

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print colored output
print_color() {
    local color=$1
    local message=$2
    echo -e "${color}${message}${NC}"
}

# Function to show usage
show_usage() {
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  --region REGION     AWS region (default: us-east-1)"
    echo "  --dry-run           List KBs without deleting them"
    echo "  --confirm           Skip confirmation prompt"
    echo "  --help              Show this help message"
    echo ""
    echo "Examples:"
    echo "  $0 --dry-run                    # List all KBs without deleting"
    echo "  $0 --region us-west-2           # Delete KBs in us-west-2"
    echo "  $0 --confirm                    # Delete without confirmation"
}

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --region)
            REGION="$2"
            shift 2
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --confirm)
            CONFIRM=true
            shift
            ;;
        --help)
            show_usage
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            show_usage
            exit 1
            ;;
    esac
done

# Check if AWS CLI is installed
if ! command -v aws &> /dev/null; then
    print_color $RED "❌ AWS CLI is not installed. Please install it first."
    exit 1
fi

# Check if AWS credentials are configured
if ! aws sts get-caller-identity &> /dev/null; then
    print_color $RED "❌ AWS credentials not configured. Please run 'aws configure' first."
    exit 1
fi

print_color $BLUE "🤖 AWS Bedrock Knowledge Base Cleaner (Bash version)"
echo "=================================================="

# List all knowledge bases
print_color $BLUE "🔍 Listing Knowledge Bases in region $REGION..."

KB_LIST=$(aws bedrock-agent list-knowledge-bases --region "$REGION" --output json 2>/dev/null)

if [ $? -ne 0 ]; then
    print_color $RED "❌ Failed to list knowledge bases. Check your permissions and region."
    exit 1
fi

# Extract knowledge base IDs and names
KB_COUNT=$(echo "$KB_LIST" | jq -r '.knowledgeBaseSummaries | length')

if [ "$KB_COUNT" -eq 0 ]; then
    print_color $GREEN "✅ No Knowledge Bases found to delete."
    exit 0
fi

print_color $YELLOW "📊 Found $KB_COUNT Knowledge Bases:"

# Display all knowledge bases
echo "$KB_LIST" | jq -r '.knowledgeBaseSummaries[] | "  - \(.name) (ID: \(.knowledgeBaseId)) - Status: \(.status)"'

if [ "$DRY_RUN" = true ]; then
    print_color $BLUE "🔍 [DRY RUN] Would delete $KB_COUNT Knowledge Bases"
    exit 0
fi

# Confirmation
if [ "$CONFIRM" = false ]; then
    echo ""
    print_color $YELLOW "⚠️  WARNING: This will delete ALL $KB_COUNT Knowledge Bases!"
    print_color $YELLOW "This action cannot be undone."
    echo -n "Are you sure you want to continue? (type 'DELETE' to confirm): "
    read -r response
    
    if [ "$response" != "DELETE" ]; then
        print_color $RED "❌ Operation cancelled."
        exit 0
    fi
fi

print_color $BLUE "🚀 Starting deletion of $KB_COUNT Knowledge Bases..."

SUCCESS_COUNT=0
FAILURE_COUNT=0

# Function to update data source deletion policy
update_data_source_policy() {
    local kb_id=$1
    local ds_id=$2
    
    print_color $YELLOW "    ⚠️  Updating data source $ds_id deletion policy to RETAIN..."
    
    # Get current data source configuration
    local ds_config=$(aws bedrock-agent get-data-source --knowledge-base-id "$kb_id" --data-source-id "$ds_id" --region "$REGION" --output json 2>/dev/null)
    
    if [ $? -eq 0 ]; then
        local ds_name=$(echo "$ds_config" | jq -r '.dataSource.name')
        local ds_config_json=$(echo "$ds_config" | jq -r '.dataSource.dataSourceConfiguration')
        
        # Update with RETAIN policy
        aws bedrock-agent update-data-source \
            --knowledge-base-id "$kb_id" \
            --data-source-id "$ds_id" \
            --name "$ds_name" \
            --data-source-configuration "$ds_config_json" \
            --data-deletion-policy RETAIN \
            --region "$REGION" &> /dev/null
        
        if [ $? -eq 0 ]; then
            print_color $GREEN "    ✅ Updated data source $ds_id deletion policy"
            return 0
        else
            print_color $RED "    ❌ Failed to update data source $ds_id deletion policy"
            return 1
        fi
    else
        print_color $RED "    ❌ Failed to get data source $ds_id configuration"
        return 1
    fi
}

# Function to delete data sources
delete_data_sources() {
    local kb_id=$1
    
    # Get data sources for this KB
    local ds_list=$(aws bedrock-agent list-data-sources --knowledge-base-id "$kb_id" --region "$REGION" --output json 2>/dev/null)
    
    if [ $? -ne 0 ]; then
        print_color $YELLOW "  ⚠️  Failed to list data sources for KB $kb_id"
        return 1
    fi
    
    local ds_count=$(echo "$ds_list" | jq -r '.dataSourceSummaries | length')
    
    if [ "$ds_count" -eq 0 ]; then
        print_color $BLUE "  📁 No data sources found"
        return 0
    fi
    
    print_color $BLUE "  📁 Found $ds_count data sources to delete first"
    
    # Delete each data source
    echo "$ds_list" | jq -r '.dataSourceSummaries[] | "\(.dataSourceId) \(.name)"' | while read -r ds_id ds_name; do
        print_color $BLUE "    🗑️  Deleting data source: $ds_name (ID: $ds_id)"
        
        # Try to delete data source
        aws bedrock-agent delete-data-source --knowledge-base-id "$kb_id" --data-source-id "$ds_id" --region "$REGION" &> /dev/null
        
        if [ $? -eq 0 ]; then
            print_color $GREEN "    ✅ Deleted data source $ds_id"
        else
            # If deletion fails, try updating policy and retry
            print_color $YELLOW "    ⚠️  Initial deletion failed, trying with RETAIN policy..."
            
            if update_data_source_policy "$kb_id" "$ds_id"; then
                sleep 2
                aws bedrock-agent delete-data-source --knowledge-base-id "$kb_id" --data-source-id "$ds_id" --region "$REGION" &> /dev/null
                
                if [ $? -eq 0 ]; then
                    print_color $GREEN "    ✅ Deleted data source $ds_id after policy update"
                else
                    print_color $RED "    ❌ Failed to delete data source $ds_id even after policy update"
                fi
            fi
        fi
    done
    
    # Wait for data sources to be fully deleted
    print_color $BLUE "    ⏳ Waiting for data source deletions to complete..."
    sleep 5
}

# Process each knowledge base
echo "$KB_LIST" | jq -r '.knowledgeBaseSummaries[] | "\(.knowledgeBaseId) \(.name)"' | while read -r kb_id kb_name; do
    print_color $BLUE "🗑️  Processing Knowledge Base: $kb_name (ID: $kb_id)"
    
    # Delete data sources first
    delete_data_sources "$kb_id"
    
    # Now delete the knowledge base itself
    RETRIES=3
    for ((i=1; i<=RETRIES; i++)); do
        aws bedrock-agent delete-knowledge-base --knowledge-base-id "$kb_id" --region "$REGION" &> /dev/null
        
        if [ $? -eq 0 ]; then
            print_color $GREEN "✅ Successfully deleted Knowledge Base: $kb_name"
            SUCCESS_COUNT=$((SUCCESS_COUNT + 1))
            break
        else
            if [ $i -lt $RETRIES ]; then
                print_color $YELLOW "⚠️  Deletion attempt $i failed, retrying in 10 seconds..."
                sleep 10
            else
                print_color $RED "❌ Failed to delete Knowledge Base $kb_name after $RETRIES attempts"
                FAILURE_COUNT=$((FAILURE_COUNT + 1))
            fi
        fi
    done
    
    # Small delay between deletions
    sleep 2
done

echo ""
print_color $BLUE "📊 Deletion Summary:"
print_color $GREEN "  ✅ Successful: $SUCCESS_COUNT"
print_color $RED "  ❌ Failed: $FAILURE_COUNT"

if [ $FAILURE_COUNT -gt 0 ]; then
    echo ""
    print_color $YELLOW "💡 For failed deletions, you might need to:"
    echo "  1. Check vector store permissions in your AWS account"
    echo "  2. Manually delete vector store resources (OpenSearch, Pinecone, etc.)"
    echo "  3. Contact AWS Support if issues persist"
fi