#!/usr/bin/env python3
"""
AWS Bedrock Knowledge Base Deletion Script v2
Enhanced version with better error handling and debugging
"""

import boto3
import time
import sys
import signal
from botocore.exceptions import ClientError, NoCredentialsError, ReadTimeoutError
from botocore.config import Config
from typing import List, Dict, Any
import argparse
import json
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FutureTimeoutError

class TimeoutHandler:
    def __init__(self, timeout_seconds=300):
        self.timeout_seconds = timeout_seconds
        self.start_time = None
        
    def __enter__(self):
        self.start_time = time.time()
        signal.signal(signal.SIGALRM, self._timeout_handler)
        signal.alarm(self.timeout_seconds)
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        signal.alarm(0)
        
    def _timeout_handler(self, signum, frame):
        raise TimeoutError(f"Operation timed out after {self.timeout_seconds} seconds")

class BedrockKBCleanerV2:
    def __init__(self, region='us-east-1', dry_run=False, debug=False):
        """
        Initialize the enhanced Bedrock KB cleaner
        """
        self.region = region
        self.dry_run = dry_run
        self.debug = debug
        
        # Configure boto3 with timeouts and retries
        config = Config(
            region_name=region,
            retries={
                'max_attempts': 3,
                'mode': 'adaptive'
            },
            read_timeout=60,
            connect_timeout=10
        )
        
        try:
            self.bedrock_client = boto3.client('bedrock-agent', config=config)
            # Test the connection
            self.bedrock_client.list_knowledge_bases(maxResults=1)
        except NoCredentialsError:
            print("❌ AWS credentials not found. Please configure your AWS credentials.")
            print("You can use: aws configure, environment variables, or IAM roles")
            sys.exit(1)
        except ClientError as e:
            print(f"❌ AWS client error: {e}")
            print("Check your permissions and region settings.")
            sys.exit(1)
    
    def debug_print(self, message):
        """Print debug messages if debug mode is enabled"""
        if self.debug:
            timestamp = time.strftime("%H:%M:%S")
            print(f"[DEBUG {timestamp}] {message}")
    
    def list_knowledge_bases(self) -> List[Dict[str, Any]]:
        """List all knowledge bases with timeout handling"""
        try:
            print(f"🔍 Listing Knowledge Bases in region {self.region}...")
            
            knowledge_bases = []
            
            with TimeoutHandler(60):  # 60 second timeout for listing
                try:
                    paginator = self.bedrock_client.get_paginator('list_knowledge_bases')
                    
                    for page_num, page in enumerate(paginator.paginate(), 1):
                        self.debug_print(f"Processing page {page_num}")
                        knowledge_bases.extend(page.get('knowledgeBaseSummaries', []))
                        
                        # Add a small delay between pages to avoid rate limiting
                        if page_num > 1:
                            time.sleep(0.5)
                            
                except Exception as e:
                    print(f"❌ Error during pagination: {e}")
                    return []
            
            print(f"📊 Found {len(knowledge_bases)} Knowledge Bases")
            
            for i, kb in enumerate(knowledge_bases, 1):
                print(f"  {i}. {kb['name']} (ID: {kb['knowledgeBaseId']}) - Status: {kb['status']}")
            
            return knowledge_bases
            
        except TimeoutError:
            print("❌ Timeout while listing knowledge bases. This might indicate a connectivity issue.")
            return []
        except ClientError as e:
            print(f"❌ Error listing knowledge bases: {e}")
            return []
    
    def list_data_sources_with_timeout(self, kb_id: str) -> List[Dict[str, Any]]:
        """List data sources with timeout handling"""
        try:
            self.debug_print(f"Listing data sources for KB {kb_id}")
            
            data_sources = []
            with TimeoutHandler(30):  # 30 second timeout for data source listing
                paginator = self.bedrock_client.get_paginator('list_data_sources')
                
                for page in paginator.paginate(knowledgeBaseId=kb_id):
                    data_sources.extend(page.get('dataSourceSummaries', []))
            
            self.debug_print(f"Found {len(data_sources)} data sources for KB {kb_id}")
            return data_sources
            
        except TimeoutError:
            print(f"    ⚠️  Timeout listing data sources for KB {kb_id}")
            return []
        except ClientError as e:
            print(f"    ⚠️  Error listing data sources for KB {kb_id}: {e}")
            return []
    
    def update_data_source_deletion_policy_with_timeout(self, kb_id: str, data_source_id: str) -> bool:
        """Update data source deletion policy with timeout"""
        try:
            self.debug_print(f"Updating deletion policy for data source {data_source_id}")
            
            with TimeoutHandler(30):
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
            
        except TimeoutError:
            print(f"    ❌ Timeout updating data source {data_source_id} deletion policy")
            return False
        except ClientError as e:
            print(f"    ⚠️  Failed to update data source {data_source_id} deletion policy: {e}")
            return False
    
    def delete_data_source_with_timeout(self, kb_id: str, data_source_id: str, max_retries: int = 3) -> bool:
        """Delete a data source with timeout and retries"""
        for attempt in range(max_retries):
            try:
                self.debug_print(f"Attempting to delete data source {data_source_id}, attempt {attempt + 1}")
                
                with TimeoutHandler(45):  # 45 second timeout for deletion
                    self.bedrock_client.delete_data_source(
                        knowledgeBaseId=kb_id,
                        dataSourceId=data_source_id
                    )
                
                print(f"    ✅ Deleted data source {data_source_id}")
                return True
                
            except TimeoutError:
                if attempt < max_retries - 1:
                    print(f"    ⚠️  Timeout on attempt {attempt + 1}, retrying...")
                    time.sleep(5)
                else:
                    print(f"    ❌ Timeout deleting data source {data_source_id} after all attempts")
                    return False
                    
            except ClientError as e:
                error_message = str(e)
                
                if 'vector store' in error_message.lower() and attempt < max_retries - 1:
                    print(f"    ⚠️  Vector store error on attempt {attempt + 1}, updating deletion policy...")
                    self.update_data_source_deletion_policy_with_timeout(kb_id, data_source_id)
                    time.sleep(3)
                    continue
                else:
                    print(f"    ❌ Failed to delete data source {data_source_id}: {error_message}")
                    return False
        
        return False
    
    def delete_knowledge_base_with_timeout(self, kb_id: str, kb_name: str, max_retries: int = 3) -> bool:
        """Delete a knowledge base with timeout handling"""
        
        if self.dry_run:
            print(f"🔍 [DRY RUN] Would delete KB: {kb_name} (ID: {kb_id})")
            return True
        
        print(f"🗑️  Deleting Knowledge Base: {kb_name} (ID: {kb_id})")
        
        # First, list and delete all data sources
        data_sources = self.list_data_sources_with_timeout(kb_id)
        
        if data_sources:
            print(f"  📁 Found {len(data_sources)} data sources to delete first")
            
            for ds in data_sources:
                ds_id = ds['dataSourceId']
                ds_name = ds['name']
                print(f"    🗑️  Deleting data source: {ds_name} (ID: {ds_id})")
                
                if not self.delete_data_source_with_timeout(kb_id, ds_id):
                    print(f"    ⚠️  Continuing despite data source deletion failure...")
        
        # Wait for data sources to be fully deleted
        if data_sources:
            print("    ⏳ Waiting for data source deletions to complete...")
            time.sleep(8)
        
        # Now delete the knowledge base itself
        for attempt in range(max_retries):
            try:
                self.debug_print(f"Attempting to delete KB {kb_id}, attempt {attempt + 1}")
                
                with TimeoutHandler(60):  # 60 second timeout for KB deletion
                    self.bedrock_client.delete_knowledge_base(knowledgeBaseId=kb_id)
                
                print(f"✅ Successfully deleted Knowledge Base: {kb_name}")
                return True
                
            except TimeoutError:
                if attempt < max_retries - 1:
                    print(f"⚠️  Timeout on deletion attempt {attempt + 1}, retrying in 15 seconds...")
                    time.sleep(15)
                else:
                    print(f"❌ Timeout deleting Knowledge Base {kb_name} after {max_retries} attempts")
                    return False
                    
            except ClientError as e:
                error_message = str(e)
                
                if attempt < max_retries - 1:
                    print(f"⚠️  Deletion attempt {attempt + 1} failed, retrying in 15 seconds...")
                    print(f"    Error: {error_message}")
                    time.sleep(15)
                else:
                    print(f"❌ Failed to delete Knowledge Base {kb_name} after {max_retries} attempts")
                    print(f"    Final error: {error_message}")
                    return False
        
        return False
    
    def delete_all_knowledge_bases(self, confirm: bool = False, batch_size: int = 5) -> None:
        """Delete all knowledge bases with improved progress tracking"""
        
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
        print(f"Processing in batches of {batch_size} to avoid overwhelming the service...")
        
        success_count = 0
        failure_count = 0
        
        # Process in batches to avoid overwhelming the service
        for batch_start in range(0, len(knowledge_bases), batch_size):
            batch_end = min(batch_start + batch_size, len(knowledge_bases))
            batch = knowledge_bases[batch_start:batch_end]
            
            print(f"\n📦 Processing batch {batch_start//batch_size + 1} ({batch_start + 1}-{batch_end} of {len(knowledge_bases)})")
            
            for i, kb in enumerate(batch):
                overall_index = batch_start + i + 1
                kb_id = kb['knowledgeBaseId']
                kb_name = kb['name']
                
                print(f"\n[{overall_index}/{len(knowledge_bases)}] Processing: {kb_name}")
                
                start_time = time.time()
                if self.delete_knowledge_base_with_timeout(kb_id, kb_name):
                    success_count += 1
                    elapsed = time.time() - start_time
                    print(f"    ⏱️  Completed in {elapsed:.1f} seconds")
                else:
                    failure_count += 1
                
                # Small delay between deletions in the same batch
                if i < len(batch) - 1:
                    time.sleep(2)
            
            # Longer delay between batches
            if batch_end < len(knowledge_bases):
                print(f"    ⏳ Waiting 10 seconds before next batch...")
                time.sleep(10)
        
        print(f"\n📊 Final Deletion Summary:")
        print(f"  ✅ Successful: {success_count}")
        print(f"  ❌ Failed: {failure_count}")
        print(f"  📈 Success Rate: {(success_count/(success_count+failure_count)*100):.1f}%")
        
        if failure_count > 0:
            print(f"\n💡 For failed deletions, you might need to:")
            print("  1. Check vector store permissions in your AWS account")
            print("  2. Manually delete vector store resources (OpenSearch, Pinecone, etc.)")
            print("  3. Contact AWS Support if issues persist")
            print("  4. Re-run this script to retry failed deletions")

def main():
    parser = argparse.ArgumentParser(description='Delete AWS Bedrock Knowledge Bases (Enhanced Version)')
    parser.add_argument('--region', default='us-east-1', help='AWS region (default: us-east-1)')
    parser.add_argument('--dry-run', action='store_true', help='List KBs without deleting them')
    parser.add_argument('--confirm', action='store_true', help='Skip confirmation prompt')
    parser.add_argument('--debug', action='store_true', help='Enable debug output')
    parser.add_argument('--batch-size', type=int, default=5, help='Number of KBs to process simultaneously (default: 5)')
    
    args = parser.parse_args()
    
    print("🤖 AWS Bedrock Knowledge Base Cleaner v2 (Enhanced)")
    print("=" * 55)
    
    if args.debug:
        print("🔧 Debug mode enabled")
    
    cleaner = BedrockKBCleanerV2(
        region=args.region, 
        dry_run=args.dry_run, 
        debug=args.debug
    )
    
    try:
        cleaner.delete_all_knowledge_bases(
            confirm=args.confirm, 
            batch_size=args.batch_size
        )
    except KeyboardInterrupt:
        print(f"\n\n⏹️  Operation interrupted by user")
        print("Some deletions may have completed. Re-run the script to continue.")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        if args.debug:
            import traceback
            traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()