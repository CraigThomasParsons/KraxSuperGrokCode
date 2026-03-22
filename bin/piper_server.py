#!/usr/bin/env python3
import http.server
import socketserver
import json
import os
import sys

# Ensure we can import from lib
script_dir = os.path.dirname(os.path.abspath(__file__))
if script_dir not in sys.path:
    sys.path.append(script_dir)

import subprocess
import shlex
from lib import fs, parser

PORT = 3000

class PiperHandler(http.server.BaseHTTPRequestHandler):
    def _set_headers(self, code=200):
        self.send_response(code)
        self.send_header('Content-type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*') # Allow extension to access
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_OPTIONS(self):
        self._set_headers()

    def do_GET(self):
        if self.path == '/job':
            # 1. Find next job
            jobs = fs.find_jobs()
            if not jobs:
                self._set_headers(200)
                self.wfile.write(json.dumps(None).encode())
                return

            job_id = jobs[0]
            try:
                # 2. Read job data
                job_data = fs.read_job_files(job_id)
                briefing = fs.compose_briefing(job_id, job_data)
                url = job_data.get("url.txt", "https://chatgpt.com/")
                
                # 3. Create run dir (if not exists)
                fs.init_run(job_id)
                
                response = {
                    "id": job_id,
                    "url": url,
                    "prompt": briefing
                }
                self._set_headers(200)
                self.wfile.write(json.dumps(response).encode())
            except Exception as e:
                print(f"Error reading job {job_id}: {e}")
                self._set_headers(500)
                self.wfile.write(json.dumps({"error": str(e)}).encode())
        else:
            self._set_headers(404)

    def do_POST(self):
        if self.path == '/job/complete':
            length = int(self.headers.get('content-length'))
            raw_data = self.rfile.read(length)
            print(f"DEBUG: Received payload size: {length}")
            
            try:
                data = json.loads(raw_data)
            except json.JSONDecodeError as e:
                print(f"DEBUG: JSON Parse Error: {e}")
                print(f"DEBUG: Raw Data: {raw_data}")
                self._set_headers(400)
                return
            
            job_id = data.get("id")
            result_text = data.get("response")
            debug_info = data.get("debug", "No debug info")
            
            print(f"DEBUG: Job ID: {job_id}")
            print(f"DEBUG: Client Log: {debug_info}")
            print(f"DEBUG: Response length: {len(result_text) if result_text else 0}")
            
            if not job_id:
                self._set_headers(400)
                return

            print(f"[*] Job {job_id} completed by Extension.")
            
            # 1. Save Response Text
            run_dir = os.path.join(fs.RUNS_DIR, job_id)
            os.makedirs(run_dir, exist_ok=True)
            
            with open(os.path.join(run_dir, "response.txt"), "w") as f:
                f.write(result_text)
                
            # 2. Parse & Execute (Phase 4.5)
            print(f"  - Parsing response...")
            actions = parser.parse_response(result_text)
            
            log_lines = []
            
            repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            scratchpad_dir = os.path.join(repo_root, "scratchpad")
            os.makedirs(scratchpad_dir, exist_ok=True)
            
            # ALLOWLIST for Phase 4.5
            ALLOWED_COMMANDS = [
                "python", "python3", 
                "pip", "pip3", 
                "node", "npm", 
                "ls", "cat", "echo", "pwd",
                "mkdir", "cp", "mv"
            ]

            for action in actions:
                try:
                    if action["type"] == "file":
                        # Validate and map to scratchpad
                        target_path = parser.validate_path(repo_root, action["path"])
                        
                        # Ensure dir exists
                        os.makedirs(os.path.dirname(target_path), exist_ok=True)
                        
                        with open(target_path, "w") as f:
                            f.write(action["content"])
                            
                        log_lines.append(f"Wrote file: {target_path}")
                        print(f"  - Wrote: {target_path}")
                        
                    elif action["type"] == "run":
                        # Controlled Execution
                        cmd_str = action["content"].strip()
                        # Split safely? For now strictly simple commands.
                        # We just check if it starts with allowed command.
                        
                        cmd_parts = shlex.split(cmd_str)
                        if not cmd_parts:
                            continue
                            
                        base_cmd = cmd_parts[0]
                        if base_cmd not in ALLOWED_COMMANDS:
                            msg = f"Skipped forbidden command: {base_cmd}"
                            log_lines.append(msg)
                            print(f"  - {msg}")
                            continue
                        
                        print(f"  - Running: {cmd_str}")
                        log_lines.append(f"CMD: {cmd_str}")
                        
                        try:
                            res = subprocess.run(
                                cmd_str, 
                                shell=True, 
                                cwd=scratchpad_dir,
                                capture_output=True,
                                text=True,
                                timeout=5,
                                stdin=subprocess.DEVNULL
                            )
                            log_lines.append(f"EXIT: {res.returncode}")
                            if res.stdout:
                                log_lines.append(f"STDOUT:\n{res.stdout}")
                            if res.stderr:
                                log_lines.append(f"STDERR:\n{res.stderr}")
                                
                        except subprocess.TimeoutExpired:
                            log_lines.append("ERROR: Timeout (5s)")
                            print("  - Timeout")
                        except Exception as e:
                            log_lines.append(f"ERROR: {e}")
                            print(f"  - Error: {e}")

                except Exception as e:
                    # Generic error catching (parsing, writing etc)
                    log_lines.append(f"Error handling action: {e}")
                    print(f"  - Error: {e}")
            
            # Save Execution Log
            with open(os.path.join(run_dir, "execution.log"), "w") as f:
                f.write("\n".join(log_lines))
                
            # 3. Handoff
            fs.write_handoff(job_id, run_dir)
            
            # 3. Archive
            fs.archive_job(job_id)
            
            self._set_headers(200)
            self.wfile.write(json.dumps({"status": "archived"}).encode())
            
        elif self.path == '/job/fail':
            length = int(self.headers.get('content-length'))
            data = json.loads(self.rfile.read(length))
            job_id = data.get("id")
            error = data.get("error")
            
            print(f"[!] Job {job_id} failed: {error}")
            fs.fail_job(job_id)
            
            self._set_headers(200)
            self.wfile.write(json.dumps({"status": "failed"}).encode())
            
        else:
            self._set_headers(404)

def run():
    print(f"[*] Piper Server running on port {PORT}")
    
    # Custom server class with SO_REUSEADDR to allow immediate port reuse
    class ReusableTCPServer(socketserver.TCPServer):
        allow_reuse_address = True
    
    with ReusableTCPServer(("", PORT), PiperHandler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n[*] Server stopped.")
        finally:
            httpd.server_close()

if __name__ == "__main__":
    run()
