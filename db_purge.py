import os
import psycopg2

def main():
    env_path = ".env"
    db_url = None
    if os.path.exists(env_path):
        with open(env_path, 'r') as f:
            for line in f:
                if line.startswith('DATABASE_URL='):
                    db_url = line.split('=', 1)[1].strip()
                    break

    if not db_url:
        print("[-] Could not find DATABASE_URL in .env")
        return

    print(f"[*] Connecting to database: {db_url[:50]}...")
    
    try:
        conn = psycopg2.connect(db_url)
        cur = conn.cursor()
        
        # 1. Clean kb_vectors
        print("[*] Deleting non-essential vectors from 'kb_vectors'...")
        cur.execute("""
            DELETE FROM kb_vectors 
            WHERE chunk_id NOT IN (
                SELECT id FROM kb WHERE source = 'API-RP 40-Core-Analysis.pdf'
            )
        """)
        vectors_deleted = cur.rowcount
        print(f"[+] Deleted {vectors_deleted} vectors.")
        
        # 2. Clean kb
        print("[*] Deleting non-essential records from 'kb'...")
        cur.execute("""
            DELETE FROM kb 
            WHERE source != 'API-RP 40-Core-Analysis.pdf'
        """)
        kb_deleted = cur.rowcount
        print(f"[+] Deleted {kb_deleted} knowledge base chunks.")
        
        # 3. Clean m (message history)
        print("[*] Deleting past conversation histories from 'm' to prevent context poisoning...")
        cur.execute("DELETE FROM m")
        messages_deleted = cur.rowcount
        print(f"[+] Deleted {messages_deleted} message history records.")
        
        # 4. Clean response_cache
        print("[*] Deleting cached responses from 'response_cache'...")
        cur.execute("DELETE FROM response_cache")
        cache_deleted = cur.rowcount
        print(f"[+] Deleted {cache_deleted} cached responses.")
        
        # 5. Clean library_docs and library_chunks (ensure pure library state)
        print("[*] Ensuring 'library_docs' and 'library_chunks' are clean...")
        cur.execute("DELETE FROM library_chunks")
        cur.execute("DELETE FROM library_docs")
        
        # Commit transaction
        conn.commit()
        print("[+] DATABASE SUCCESSFULLY PURGED AND RESTORED TO PURE SOURCE-OF-TRUTH STATE!")
        
    except Exception as e:
        print(f"[-] Database operation failed: {e}")
        if 'conn' in locals() and conn:
            conn.rollback()
    finally:
        if 'cur' in locals() and cur:
            cur.close()
        if 'conn' in locals() and conn:
            conn.close()

if __name__ == "__main__":
    main()
