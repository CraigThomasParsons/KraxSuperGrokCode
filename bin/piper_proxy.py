#!/usr/bin/env python3
import sys
import os
import time
import argparse
import traceback

# Ensure we can import from lib and drivers
script_dir = os.path.dirname(os.path.abspath(__file__))
if script_dir not in sys.path:
    sys.path.append(script_dir)

from lib import fs
# Import the specific driver (Future: Factory pattern)
from drivers.desktop_x11 import DesktopX11Driver

def process_job(job_id):
    print(f"[*] Processing Job: {job_id}")
    run_dir = ""
    try:
        # 1. Read Job
        print(f"  - Reading job files...")
        job_data = fs.read_job_files(job_id)
        briefing = fs.compose_briefing(job_id, job_data)
        
        # 2. Init Run
        run_dir = fs.init_run(job_id)
        print(f"  - Run directory created: {run_dir}")
        
        # 3. Initialize Driver
        driver = DesktopX11Driver()
        
        # 4. Open Chat
        target_url = job_data.get("url.txt", "https://chatgpt.com/")
        driver.open_chat(target_url)
        
        # 5. Focus Input
        driver.focus_input()
        
        # 6. Type Briefing
        driver.type_text(briefing)
        
        # 7. Send
        driver.send()
        
        # 8. Wait for response (blind wait)
        print(f"  - Waiting for response...")
        time.sleep(10)
        
        # 9. Capture Evidence
        screenshot_path = os.path.join(run_dir, "snapshot.png")
        driver.screenshot(screenshot_path)
        
        # 10. Record Handoff
        fs.write_handoff(job_id, run_dir)
        print(f"  - Handoff written.")
        
        # 11. Archive
        fs.archive_job(job_id)
        print(f"  - Job archived.")
        
    except Exception as e:
        print(f"[!] Error processing job {job_id}: {e}")
        traceback.print_exc()
        try:
            fs.fail_job(job_id)
            print(f"  - Job moved to failed.")
        except:
            print("  - Could not move to failed.")

def main():
    parser = argparse.ArgumentParser(description="Piper Proxy Agent")
    parser.add_argument("--once", action="store_true", help="Process one job and exit")
    args = parser.parse_args()
    
    # scan for jobs
    while True:
        jobs = fs.find_jobs()
        if not jobs:
            print("[*] No jobs in inbox.")
            break
            
        # Process the first job
        job = jobs[0]
        process_job(job)
        
        if args.once:
            break
        
if __name__ == "__main__":
    main()
