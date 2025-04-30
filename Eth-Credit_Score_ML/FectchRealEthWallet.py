import pandas as pd
from tqdm import tqdm
import json
from web3 import Web3
from Eth_Credit_Score import EthereumCreditScorer
import time
import os
from multiprocessing import Pool, cpu_count
import functools

# ========== CONFIGURATION ========== #
INFURA_URL = "https://mainnet.infura.io/v3/af423287a003493f862148da13f7e798"
ETHERSCAN_API_KEY = "DMXFNRAC6FEGMGGE68VRWCD6R5EB9RXV6D"
INPUT_FILE = "real_eth_addresses.txt"
REPORT_FOLDER = "wallet_reports"
MAX_RETRIES = 2
RETRY_DELAY = 1
CACHE_FILE = "processed_cache.json"
WORKERS = cpu_count() * 2  # Double the CPU cores for IO-bound tasks

def load_wallet_addresses(file_path):
    """Load wallet addresses from text file"""
    with open(file_path, 'r') as f:
        addresses = [line.strip() for line in f if line.strip()]
    return list(set(addresses))  # Remove duplicates

def load_processed_cache():
    """Load already processed addresses from cache"""
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, 'r') as f:
            return json.load(f)
    return {'processed': [], 'failed': []}

def save_processed_cache(cache):
    """Save processed addresses to cache"""
    with open(CACHE_FILE, 'w') as f:
        json.dump(cache, f)

def validate_address(address, web3):
    """Validate and checksum a single Ethereum address"""
    if web3.is_address(address):
        return web3.to_checksum_address(address)
    return None

def generate_report(address, wallet_data, score):
    """Generate report text for a single wallet"""
    report = [
        f"Address: {address}",
        "",
        "=== ACCOUNT OVERVIEW ===",
        f"• Age: {wallet_data['account_age_days']:.1f} days",
        f"• Balance: {wallet_data['eth_balance']:.4f} ETH",
        f"• Transactions: {wallet_data['tx_count']}",
        f"• Success Rate: {wallet_data['tx_success_rate']:.2%}",
        f"• Token Diversity: {wallet_data['token_diversity']}",
        f"• DeFi Interactions: {wallet_data['defi_interactions']}",
        "",
        "=== SECURITY ANALYSIS ===",
        f"• Malicious Interactions: {wallet_data['_security_data']['malicious']['count']}",
        "",
        f"• Mixer Transactions: {wallet_data['_security_data']['mixer']['count']}",
        "",
        "=== REPUTATION-BACKED DELEGATION ===",
        f"• Delegation Capacity: {wallet_data['delegation_capacity']:.2f} points",
        f"• Staked Collateral: {wallet_data['staked_collateral']:.4f} ETH",
        f"• Reputation Score: {wallet_data['reputation_score']:.2f}/1.0",
        f"• Successful Delegations: {wallet_data['delegation_success_rate']:.2%}",
        f"• Uses ZKP: {'Yes' if wallet_data['zkp_usage'] else 'No'}",
        "",
        "=" * 60,
        f"💳 FINAL CREDIT SCORE: {int(score)}/1000",
        get_score_interpretation(score)
    ]
    return "\n".join(report)

def get_score_interpretation(score):
    """Get interpretation text for score"""
    if score >= 850: return "💎 Excellent - Exceptional creditworthiness"
    if score >= 700: return "👍 Very Good - Strong financial history"
    if score >= 550: return "🆗 Good - Reliable with minor risks"
    if score >= 400: return "⚠️ Fair - Elevated risk factors"
    return "❌ Poor - High risk profile"

def process_wallet_task(args):
    """Task for parallel processing of a single wallet"""
    address, web3_provider, retry_count = args
    web3 = Web3(Web3.HTTPProvider(web3_provider))
    scorer = EthereumCreditScorer()
    
    for attempt in range(retry_count):
        try:
            wallet_data = scorer.fetch_wallet_data(address)
            if not wallet_data:
                return address, None, None
            
            score = scorer.predict_score(wallet_data)
            report = generate_report(address, wallet_data, score)
            return address, report, score
            
        except Exception as e:
            if attempt == retry_count - 1:
                print(f"\nFailed to process {address} after {retry_count} attempts")
                return address, None, None
            time.sleep(RETRY_DELAY * (attempt + 1))

def main():
    print("=== High-Performance Ethereum Wallet Analyzer ===")
    print(f"Using {WORKERS} parallel workers")
    
    # Initialize Web3 connection check
    web3 = Web3(Web3.HTTPProvider(INFURA_URL))
    if not web3.is_connected():
        raise ConnectionError("Failed to connect to Ethereum node")
    
    # Create reports folder
    os.makedirs(REPORT_FOLDER, exist_ok=True)
    
    # Load and validate addresses
    print(f"Loading addresses from {INPUT_FILE}...")
    raw_addresses = load_wallet_addresses(INPUT_FILE)
    cache = load_processed_cache()
    
    # Filter out already processed addresses
    new_addresses = [addr for addr in raw_addresses if addr not in cache['processed'] and addr not in cache['failed']]
    valid_addresses = []
    invalid_addresses = []
    
    for addr in new_addresses:
        validated = validate_address(addr, web3)
        if validated:
            valid_addresses.append(validated)
        else:
            invalid_addresses.append(addr)
    
    print(f"\nTotal addresses: {len(raw_addresses)}")
    print(f"Already processed: {len(cache['processed'])}")
    print(f"New valid addresses: {len(valid_addresses)}")
    print(f"Invalid addresses: {len(invalid_addresses)}")
    
    if invalid_addresses:
        with open(os.path.join(REPORT_FOLDER, "invalid_addresses.txt"), "w") as f:
            f.write("\n".join(invalid_addresses))
    
    # Process wallets in parallel
    print("\nProcessing wallets...")
    start_time = time.time()
    
    # Prepare tasks for parallel processing
    tasks = [(addr, INFURA_URL, MAX_RETRIES) for addr in valid_addresses]
    
    results = []
    with Pool(WORKERS) as pool:
        with tqdm(total=len(valid_addresses), desc="Processing") as pbar:
            for address, report, score in pool.imap_unordered(process_wallet_task, tasks):
                if report is not None:
                    # Save successful reports
                    filename = f"report_{address}.txt"
                    with open(os.path.join(REPORT_FOLDER, filename), "w") as f:
                        f.write(report)
                    results.append({'address': address, 'score': score})
                    cache['processed'].append(address)
                else:
                    cache['failed'].append(address)
                pbar.update(1)
    
    # Save cache
    save_processed_cache(cache)
    
    # Generate summary
    if results:
        df = pd.DataFrame(results)
        df.to_csv(os.path.join(REPORT_FOLDER, "summary.csv"), index=False)
        
        elapsed = time.time() - start_time
        speed = len(results) / elapsed if elapsed > 0 else 0
        
        print("\n=== Processing Summary ===")
        print(f"Processed {len(results)} wallets in {elapsed:.1f} seconds")
        print(f"Processing speed: {speed:.1f} wallets/second")
        print(f"Average Score: {df['score'].mean():.1f}")
        print(f"Median Score: {df['score'].median():.1f}")
        print("\nScore Distribution:")
        print(df['score'].value_counts(bins=10, sort=False))
    
    print("\n=== Completed ===")
    print(f"Reports saved to: {REPORT_FOLDER}")

if __name__ == "__main__":
    main()
