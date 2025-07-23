#!/usr/bin/env python3
"""
AWS Bedrock Knowledge Base Deletion Script

This script deletes all AWS Bedrock Knowledge Bases in your account.
It handles common deletion issues like vector store configuration problems
by updating data deletion policies and retrying operations.
"""

import boto3
import time
import sys
from botocore.exceptions import ClientError, NoCredentialsError
from typing import List, Dict, Any
import argparse
import json

class BedrockKBCleaner:
    def __init__(self, region='us-east-1', dry_run=False):
        """
        Initialize the Bedrock KB cleaner
        
        Args:
            region: AWS region to operate in
            dry_run: If True, only list KBs without deleting
        """
        self.region = region
        self.dry_run = dry_run
        
        try:
            self.bedrock_client = boto3.client('bedrock-agent', region_name=region)
        except NoCredentialsError:
            print("❌ AWS credentials not found. Please configure your AWS credentials.")
            print("You can use: aws configure, environment variables, or IAM roles")
            sys.exit(1)
    
    def list_knowledge_bases(self) -> List[Dict[str, Any]]:
        """List all knowledge bases in the account"""
        try:
            print(f"🔍 Listing Knowledge Bases in region {self.region}...")
            
            knowledge_bases = []
            paginator = self.bedrock_client.get_paginator('list_knowledge_bases')
            
            for page in paginator.paginate():
                knowledge_bases.extend(page.get('knowledgeBaseSummaries', []))
            
            print(f"📊 Found {len(knowledge_bases)} Knowledge Bases")
            
            for i, kb in enumerate(knowledge_bases, 1):
                print(f"  {i}. {kb['name']} (ID: {kb['knowledgeBaseId']}) - Status: {kb['status']}")
            
            return knowledge_bases
            
        except ClientError as e:
            print(f"❌ Error listing knowledge bases: {e}")
            return []
    
    def list_data_sources(self, kb_id: str) -> List[Dict[str, Any]]:
        """List all data sources for a knowledge base"""
        try:
            data_sources = []
            paginator = self.bedrock_client.get_paginator('list_data_sources')
            
            for page in paginator.paginate(knowledgeBaseId=kb_id):
                data_sources.extend(page.get('dataSourceSummaries', []))
            
            return data_sources
            
        except ClientError as e:
            print(f"⚠️  Error listing data sources for KB {kb_id}: {e}")
            return []
    
    def update_data_source_deletion_policy(self, kb_id: str, data_source_id: str) -> bool:
        """Update data source deletion policy to RETAIN to avoid vector store issues"""
        try:
            # Get current data source configuration
            response = self.bedrock_client.get_data_source(
                knowledgeBaseId=kb_id,
                dataSourceId=data_source_id
            )
            
            data_source = response['dataSource']
            
            # Update the deletion policy to RETAIN
            self.bedrock_client.update_data_source(
                knowledgeBaseId=kb_id,
                dataSourceId=data_source_id,
                name=data_source['name'],
                dataSourceConfiguration=data_source['dataSourceConfiguration'],
                dataDeletionPolicy='RETAIN'
            )
            
            print(f"    ✅ Updated data source {data_source_id} deletion policy to RETAIN")
            return True
            
        except ClientError as e:
            print(f"    ⚠️  Failed to update data source {data_source_id} deletion policy: {e}")
            return False
    
    def delete_data_source(self, kb_id: str, data_source_id: str, max_retries: int = 3) -> bool:
        """Delete a data source with retries"""
        for attempt in range(max_retries):
            try:
                self.bedrock_client.delete_data_source(
                    knowledgeBaseId=kb_id,
                    dataSourceId=data_source_id
                )
                
                print(f"    ✅ Deleted data source {data_source_id}")
                return True
                
            except ClientError as e:
                error_code = e.response['Error']['Code']
                error_message = e.response['Error']['Message']
                
                if 'vector store' in error_message.lower() and attempt < max_retries - 1:
                    print(f"    ⚠️  Vector store error on attempt {attempt + 1}, updating deletion policy...")
                    self.update_data_source_deletion_policy(kb_id, data_source_id)
                    time.sleep(2)
                    continue
                else:
                    print(f"    ❌ Failed to delete data source {data_source_id}: {error_message}")
                    return False
        
        return False
    
    def delete_knowledge_base(self, kb_id: str, kb_name: str, max_retries: int = 3) -> bool:
        """Delete a knowledge base with all its data sources"""
        
        if self.dry_run:
            print(f"🔍 [DRY RUN] Would delete KB: {kb_name} (ID: {kb_id})")
            return True
        
        print(f"🗑️  Deleting Knowledge Base: {kb_name} (ID: {kb_id})")
        
        # First, list and delete all data sources
        data_sources = self.list_data_sources(kb_id)
        
        if data_sources:
            print(f"  📁 Found {len(data_sources)} data sources to delete first")
            
            for ds in data_sources:
                ds_id = ds['dataSourceId']
                ds_name = ds['name']
                print(f"    🗑️  Deleting data source: {ds_name} (ID: {ds_id})")
                
                if not self.delete_data_source(kb_id, ds_id):
                    print(f"    ⚠️  Continuing despite data source deletion failure...")
        
        # Wait a bit for data sources to be fully deleted
        if data_sources:
            print("    ⏳ Waiting for data source deletions to complete...")
            time.sleep(5)
        
        # Now delete the knowledge base itself
        for attempt in range(max_retries):
            try:
                self.bedrock_client.delete_knowledge_base(knowledgeBaseId=kb_id)
                print(f"✅ Successfully deleted Knowledge Base: {kb_name}")
                return True
                
            except ClientError as e:
                error_code = e.response['Error']['Code']
                error_message = e.response['Error']['Message']
                
                if attempt < max_retries - 1:
                    print(f"⚠️  Deletion attempt {attempt + 1} failed, retrying in 10 seconds...")
                    print(f"    Error: {error_message}")
                    time.sleep(10)
                else:
                    print(f"❌ Failed to delete Knowledge Base {kb_name} after {max_retries} attempts")
                    print(f"    Final error: {error_message}")
                    return False
        
        return False
    
    def delete_all_knowledge_bases(self, confirm: bool = False) -> None:
        """Delete all knowledge bases in the account"""
        
        knowledge_bases = self.list_knowledge_bases()
        
        if not knowledge_bases:
            print("✅ No Knowledge Bases found to delete.")
            return
        
        if not self.dry_run and not confirm:
            print(f"\n⚠️  WARNING: This will delete ALL {len(knowledge_bases)} Knowledge Bases!")
            print("This action cannot be undone.")
            response = input("Are you sure you want to continue? (type 'DELETE' to confirm): ")
            
            if response != 'DELETE':
                print("❌ Operation cancelled.")
                return
        
        print(f"\n🚀 Starting deletion of {len(knowledge_bases)} Knowledge Bases...")
        
        success_count = 0
        failure_count = 0
        
        for i, kb in enumerate(knowledge_bases, 1):
            kb_id = kb['knowledgeBaseId']
            kb_name = kb['name']
            
            print(f"\n[{i}/{len(knowledge_bases)}] Processing: {kb_name}")
            
            if self.delete_knowledge_base(kb_id, kb_name):
                success_count += 1
            else:
                failure_count += 1
            
            # Small delay between deletions to avoid rate limiting
            if not self.dry_run and i < len(knowledge_bases):
                time.sleep(2)
        
        print(f"\n📊 Deletion Summary:")
        print(f"  ✅ Successful: {success_count}")
        print(f"  ❌ Failed: {failure_count}")
        
        if failure_count > 0:
            print(f"\n💡 For failed deletions, you might need to:")
            print("  1. Check vector store permissions in your AWS account")
            print("  2. Manually delete vector store resources (OpenSearch, Pinecone, etc.)")
            print("  3. Contact AWS Support if issues persist")

def main():
    parser = argparse.ArgumentParser(description='Delete AWS Bedrock Knowledge Bases')
    parser.add_argument('--region', default='us-east-1', help='AWS region (default: us-east-1)')
    parser.add_argument('--dry-run', action='store_true', help='List KBs without deleting them')
    parser.add_argument('--confirm', action='store_true', help='Skip confirmation prompt')
    parser.add_argument('--list-regions', action='store_true', help='List common AWS regions with Bedrock')
    
    args = parser.parse_args()
    
    if args.list_regions:
        print("Common AWS regions with Bedrock support:")
        regions = [
            'us-east-1', 'us-west-2', 'eu-west-1', 'eu-central-1', 
            'ap-southeast-1', 'ap-northeast-1', 'ca-central-1'
        ]
        for region in regions:
            print(f"  - {region}")
        return
    
    print("🤖 AWS Bedrock Knowledge Base Cleaner")
    print("=" * 50)
    
    cleaner = BedrockKBCleaner(region=args.region, dry_run=args.dry_run)
    cleaner.delete_all_knowledge_bases(confirm=args.confirm)

if __name__ == "__main__":
    main()