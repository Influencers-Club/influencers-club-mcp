"""
HTTP upload server for batch CSV file uploads.

Runs alongside the MCP server to accept file uploads via browser,
bypassing Claude's context window limitations for large CSV files.
"""

import json
import os
import re
import sys
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

def _is_docker() -> bool:
    """Detect if running inside a Docker container."""
    return os.path.exists("/.dockerenv") or os.path.exists("/run/.containerenv")

_REPO_DIR = str(Path(__file__).resolve().parent.parent)
_DEFAULT_EXPORTS = "/exports" if _is_docker() else os.path.join(_REPO_DIR, "exports")
_DEFAULT_IMPORTS = "/imports" if _is_docker() else os.path.join(_REPO_DIR, "imports")

OUTPUT_DIR = os.environ.get("OUTPUT_DIR", _DEFAULT_EXPORTS)
IMPORTS_DIR = os.environ.get("IMPORTS_DIR", _DEFAULT_IMPORTS)
UPLOAD_PORT = int(os.environ.get("UPLOAD_PORT", "8090"))
# Default to 127.0.0.1 (localhost only) for safety. Set to 0.0.0.0 inside Docker
# where the host-side restriction is handled by Docker's -p 127.0.0.1:port:port mapping.
UPLOAD_BIND = os.environ.get("UPLOAD_BIND", "127.0.0.1")
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB


def _log(msg: str) -> None:
    print(f"[Upload] {msg}", file=sys.stderr)


def _sanitize_filename(name: str) -> str:
    """Sanitize filename to prevent path traversal."""
    name = os.path.basename(name)
    name = re.sub(r'[^\w\-.]', '_', name)
    if not name.lower().endswith('.csv'):
        name += '.csv'
    if len(name) > 100:
        name = name[:96] + '.csv'
    return name or 'upload.csv'


def _count_csv_rows(content: bytes) -> int:
    """Count data rows in CSV content (excluding header)."""
    try:
        text = content.decode('utf-8', errors='replace')
        lines = [line for line in text.strip().split('\n') if line.strip()]
        return max(0, len(lines) - 1)
    except Exception:
        return 0


def _get_export_host_dir() -> str:
    config_file = os.path.join(OUTPUT_DIR, '.ic_config.json')
    if os.path.exists(config_file):
        try:
            with open(config_file) as f:
                cfg = json.load(f)
            return cfg.get('export_host_dir', '')
        except (json.JSONDecodeError, OSError):
            pass
    return os.environ.get('EXPORT_HOST_DIR', '')


# ─── Upload page HTML ─────────────────────────────────────────────────

UPLOAD_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Influencers Club &mdash; Batch Upload</title>
<link rel="icon" href="https://dashboard.influencers.club/static/media/Logo.4503ee35c0f3d2e4c512d6f839b9e9da.svg" type="image/svg+xml">
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
*{margin:0;padding:0;box-sizing:border-box}
body{
  font-family:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
  background:#0f1629;color:#c8d6e5;min-height:100vh;
  display:flex;flex-direction:column;align-items:center;justify-content:center;
  padding:20px;position:relative;
}
.container{width:100%;max-width:520px;position:relative;z-index:1}
.logo{text-align:center;margin-bottom:28px;animation:fadeIn .5s ease}
@keyframes fadeIn{from{opacity:0;transform:translateY(-12px)}to{opacity:1;transform:translateY(0)}}
.logo-icon{
  width:48px;height:48px;margin:0 auto 12px;
}
.logo-icon img{width:100%;height:100%;border-radius:12px}
.logo h1{
  font-size:20px;font-weight:700;color:#fff;letter-spacing:.5px;
}
.logo p{color:#5a6a8a;font-size:13px;margin-top:4px;font-weight:400}
.card{
  background:#182038;
  border:1px solid rgba(255,255,255,.06);
  border-radius:16px;padding:28px;
  box-shadow:0 2px 20px rgba(0,0,0,.3);
  animation:fadeUp .5s ease .05s both;
}
@keyframes fadeUp{from{opacity:0;transform:translateY(12px)}to{opacity:1;transform:translateY(0)}}
.section-label{
  font-size:11px;color:#4e7fff;text-transform:uppercase;
  letter-spacing:1px;font-weight:600;margin-bottom:16px;
}
.drop-zone{
  border:2px dashed rgba(78,127,255,.25);border-radius:12px;
  padding:44px 24px;text-align:center;cursor:pointer;
  transition:all .25s ease;
  background:rgba(78,127,255,.04);
}
.drop-zone:hover{
  border-color:rgba(78,127,255,.5);
  background:rgba(78,127,255,.07);
}
.drop-zone.drag-over{
  border-color:#4e7fff;border-style:solid;
  background:rgba(78,127,255,.1);
  transform:scale(1.01);
}
.drop-icon{margin-bottom:14px}
.drop-icon svg{width:48px;height:48px}
.drop-text{font-size:15px;font-weight:600;margin-bottom:4px;color:#e4eaf5}
.drop-hint{font-size:12px;color:#5a6a8a;font-weight:400}
.file-info{
  display:none;margin-top:16px;padding:12px 14px;
  background:rgba(78,127,255,.08);border-radius:10px;
  border:1px solid rgba(78,127,255,.15);
  align-items:center;gap:10px;
  animation:slideIn .25s ease;
}
@keyframes slideIn{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:translateY(0)}}
.file-info.visible{display:flex}
.file-icon-wrap{
  width:38px;height:38px;
  background:#4e7fff;
  border-radius:8px;
  display:flex;align-items:center;justify-content:center;flex-shrink:0;
}
.file-icon-wrap svg{width:18px;height:18px}
.file-details{flex:1;min-width:0}
.file-name{font-weight:600;font-size:13px;color:#e4eaf5;word-break:break-all}
.file-meta{font-size:11px;color:#5a6a8a;margin-top:2px}
.btn{
  display:none;width:100%;padding:13px;margin-top:16px;border:none;
  border-radius:10px;font-size:14px;font-weight:600;cursor:pointer;
  transition:all .2s ease;
  background:#4e7fff;color:#fff;
}
.btn.visible{display:block}
.btn:hover{background:#3d6df0;box-shadow:0 4px 16px rgba(78,127,255,.3)}
.btn:active{transform:scale(.985)}
.btn:disabled{opacity:.5;cursor:not-allowed;transform:none;box-shadow:none}
.success{display:none;text-align:center;padding:20px 0;animation:fadeUp .4s ease}
.success.visible{display:block}
.success-icon{
  width:64px;height:64px;
  background:rgba(52,211,153,.1);
  border:2px solid rgba(52,211,153,.3);border-radius:50%;
  display:flex;align-items:center;justify-content:center;
  margin:0 auto 16px;
  animation:pop .4s cubic-bezier(.175,.885,.32,1.275);
}
@keyframes pop{0%{transform:scale(0)}100%{transform:scale(1)}}
.success-icon svg{width:28px;height:28px}
.success-title{font-size:20px;font-weight:700;color:#34d399;margin-bottom:10px}
.success-details{font-size:13px;color:#8899b0;margin-bottom:16px;line-height:1.6}
.instruction-box{
  background:rgba(78,127,255,.06);border:1px solid rgba(78,127,255,.12);
  border-radius:10px;padding:16px;margin-top:14px;text-align:left;
}
.instruction-label{
  font-size:10px;color:#4e7fff;text-transform:uppercase;
  letter-spacing:.8px;font-weight:600;margin-bottom:6px;
}
.instruction-text{font-size:13px;font-weight:500;color:#a0b0c8;line-height:1.6}
.instruction-text em{font-style:normal;color:#4e7fff;font-weight:600}
.error-msg{
  display:none;margin-top:14px;padding:10px 14px;
  background:rgba(239,68,68,.08);border:1px solid rgba(239,68,68,.15);
  border-radius:8px;color:#f87171;font-size:13px;
  animation:shake .35s ease;
}
@keyframes shake{0%,100%{transform:translateX(0)}25%{transform:translateX(-3px)}75%{transform:translateX(3px)}}
.error-msg.visible{display:block}
.spinner{
  display:inline-block;width:16px;height:16px;
  border:2px solid rgba(255,255,255,.2);border-top-color:#fff;
  border-radius:50%;animation:spin .6s linear infinite;
  margin-right:8px;vertical-align:middle;
}
@keyframes spin{to{transform:rotate(360deg)}}
input[type="file"]{display:none}
.upload-another{
  display:none;margin-top:14px;
  background:transparent;
  border:1px solid rgba(78,127,255,.2);color:#5a6a8a;padding:9px 18px;
  border-radius:8px;cursor:pointer;font-size:12px;font-weight:500;
  transition:all .2s;
}
.upload-another:hover{border-color:#4e7fff;color:#4e7fff}
.upload-another.visible{display:inline-block}
.footer{
  margin-top:20px;text-align:center;font-size:11px;color:#3a4a66;
  position:relative;z-index:1;
}
.footer a{color:#4e7fff;text-decoration:none;font-weight:500}
.footer a:hover{text-decoration:underline}
</style>
</head>
<body>
<div class="container">
  <div class="logo">
    <div class="logo-icon">
      <img src="https://dashboard.influencers.club/static/media/Logo.4503ee35c0f3d2e4c512d6f839b9e9da.svg" alt="Influencers.club">
    </div>
    <h1>Influencers.club</h1>
    <p>Batch File Upload</p>
  </div>
  <div class="card">
    <div class="section-label">Data Enrichment</div>
    <div id="uploadArea">
      <div class="drop-zone" id="dropZone">
        <div class="drop-icon">
          <svg viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg">
            <rect x="8" y="4" width="32" height="40" rx="4" fill="rgba(78,127,255,.1)" stroke="#4e7fff" stroke-width="1.5"/>
            <path d="M18 20h12M18 26h12M18 32h8" stroke="#4e7fff" stroke-width="1.5" stroke-linecap="round"/>
            <circle cx="36" cy="12" r="8" fill="#4e7fff"/>
            <path d="M36 8.5v7m-3.5-3.5h7" stroke="white" stroke-width="1.8" stroke-linecap="round"/>
          </svg>
        </div>
        <div class="drop-text">Drop your CSV file here</div>
        <div class="drop-hint">or click to browse &middot; .csv files only &middot; up to 10,000 rows</div>
      </div>
      <input type="file" id="fileInput" accept=".csv">
      <div class="file-info" id="fileInfo">
        <div class="file-icon-wrap">
          <svg viewBox="0 0 20 20" fill="none"><path d="M4 2h8l4 4v12a2 2 0 01-2 2H4a2 2 0 01-2-2V4a2 2 0 012-2z" fill="white" fill-opacity=".9"/><path d="M12 2l4 4h-4V2z" fill="white" fill-opacity=".5"/></svg>
        </div>
        <div class="file-details">
          <div class="file-name" id="fileName"></div>
          <div class="file-meta" id="fileMeta"></div>
        </div>
      </div>
      <div class="error-msg" id="errorMsg"></div>
      <button class="btn" id="uploadBtn">Add new CSV +</button>
    </div>
    <div class="success" id="successState">
      <div class="success-icon">
        <svg viewBox="0 0 32 32" fill="none"><path d="M7 16l6 6L25 8" stroke="#34d399" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/></svg>
      </div>
      <div class="success-title">Upload Complete</div>
      <div class="success-details" id="successDetails"></div>
      <div class="instruction-box">
        <div class="instruction-label">What happens next</div>
        <div class="instruction-text">
          Claude will <em>automatically detect</em> your file and start processing.
          Go back to your Claude Desktop window.
        </div>
      </div>
      <button class="upload-another" id="uploadAnother">Upload another file</button>
    </div>
  </div>
  <div class="footer">Powered by <a href="https://influencers.club" target="_blank">Influencers.club</a></div>
</div>
<script>
const dropZone=document.getElementById('dropZone'),
  fileInput=document.getElementById('fileInput'),
  fileInfo=document.getElementById('fileInfo'),
  fileNameEl=document.getElementById('fileName'),
  fileMeta=document.getElementById('fileMeta'),
  uploadBtn=document.getElementById('uploadBtn'),
  errorMsg=document.getElementById('errorMsg'),
  uploadArea=document.getElementById('uploadArea'),
  successState=document.getElementById('successState'),
  successDetails=document.getElementById('successDetails'),
  uploadAnother=document.getElementById('uploadAnother');

let selectedFile=null;

dropZone.addEventListener('click',()=>fileInput.click());
dropZone.addEventListener('dragover',e=>{e.preventDefault();dropZone.classList.add('drag-over')});
dropZone.addEventListener('dragleave',()=>dropZone.classList.remove('drag-over'));
dropZone.addEventListener('drop',e=>{
  e.preventDefault();dropZone.classList.remove('drag-over');
  if(e.dataTransfer.files.length>0)handleFile(e.dataTransfer.files[0]);
});
fileInput.addEventListener('change',e=>{
  if(e.target.files.length>0)handleFile(e.target.files[0]);
});
uploadBtn.addEventListener('click',doUpload);
uploadAnother.addEventListener('click',resetUpload);

function handleFile(file){
  hideError();
  if(!file.name.toLowerCase().endsWith('.csv')){showError('Please select a .csv file');return}
  if(file.size>50*1024*1024){showError('File too large. Maximum: 50 MB');return}
  selectedFile=file;
  const reader=new FileReader();
  reader.onload=e=>{
    let text=e.target.result;
    if(text.charCodeAt(0)===0xFEFF)text=text.slice(1);
    const lines=text.trim().split('\\n').filter(l=>l.trim());
    if(lines.length<2){showError('CSV must have a header and at least one data row');selectedFile=null;return}
    const rows=lines.length-1;
    fileNameEl.textContent=file.name;
    fileMeta.textContent=rows.toLocaleString()+' rows \\u00b7 '+formatSize(file.size);
    fileInfo.classList.add('visible');
    uploadBtn.classList.add('visible');
  };
  reader.readAsText(file);
}

async function doUpload(){
  if(!selectedFile)return;
  uploadBtn.disabled=true;
  uploadBtn.innerHTML='<span class="spinner"></span>Uploading\\u2026';
  hideError();
  try{
    const resp=await fetch('/upload',{
      method:'POST',
      headers:{'X-Filename':selectedFile.name,'Content-Type':'text/csv'},
      body:selectedFile,
    });
    const data=await resp.json();
    if(!resp.ok||data.error)throw new Error(data.message||'Upload failed');
    uploadArea.style.display='none';
    successDetails.innerHTML='<strong>'+data.filename+'</strong><br>'+
      data.rows.toLocaleString()+' rows uploaded successfully';
    successState.classList.add('visible');
    uploadAnother.classList.add('visible');
  }catch(err){
    showError(err.message);
    uploadBtn.disabled=false;
    uploadBtn.textContent='Upload File';
  }
}

function resetUpload(){
  selectedFile=null;fileInput.value='';
  fileInfo.classList.remove('visible');
  uploadBtn.classList.remove('visible');
  uploadBtn.disabled=false;uploadBtn.textContent='Upload File';
  successState.classList.remove('visible');
  uploadAnother.classList.remove('visible');
  uploadArea.style.display='block';hideError();
}

function showError(m){errorMsg.textContent=m;errorMsg.classList.add('visible')}
function hideError(){errorMsg.classList.remove('visible')}
function formatSize(b){
  if(b<1024)return b+' B';
  if(b<1048576)return(b/1024).toFixed(1)+' KB';
  return(b/1048576).toFixed(1)+' MB';
}
</script>
</body>
</html>
"""


# ─── HTTP handler ──────────────────────────────────────────────────────

class UploadHandler(BaseHTTPRequestHandler):
    """Handles file uploads and serves the upload page."""

    def do_GET(self):
        if self.path == '/':
            self._serve_html()
        elif self.path == '/api/files':
            self._list_files()
        elif self.path == '/health':
            self._send_json(200, {'status': 'ok'})
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path == '/upload':
            self._handle_upload()
        else:
            self.send_error(404)

    def do_OPTIONS(self):
        self.send_response(204)
        self.end_headers()

    # ── Handlers ──

    def _serve_html(self):
        body = UPLOAD_HTML.encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-cache')
        self.end_headers()
        self.wfile.write(body)

    def _list_files(self):
        """List CSV files in the imports directory."""
        try:
            imports = Path(IMPORTS_DIR)
            files = []
            if imports.exists():
                for f in sorted(imports.glob('*.csv'), key=lambda p: p.stat().st_mtime, reverse=True)[:5]:
                    stat = f.stat()
                    rows = _count_csv_rows(f.read_bytes()) if stat.st_size < 10 * 1024 * 1024 else -1
                    files.append({
                        'filename': f.name,
                        'size_bytes': stat.st_size,
                        'rows': rows,
                        'modified': time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(stat.st_mtime)),
                    })
            self._send_json(200, {'files': files})
        except Exception as e:
            self._send_json(500, {'error': True, 'message': str(e)})

    def _handle_upload(self):
        """Receive a CSV file and save it to the exports directory."""
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            if content_length <= 0:
                self._send_json(400, {'error': True, 'message': 'Empty request body'})
                return
            if content_length > MAX_FILE_SIZE:
                self._send_json(413, {'error': True, 'message': f'File too large. Max: {MAX_FILE_SIZE // (1024 * 1024)} MB'})
                return

            raw_filename = self.headers.get('X-Filename', 'upload.csv')
            filename = _sanitize_filename(raw_filename)

            body = self.rfile.read(content_length)

            # Validate UTF-8 text
            try:
                text = body.decode('utf-8-sig')  # utf-8-sig strips BOM automatically
            except UnicodeDecodeError:
                self._send_json(400, {'error': True, 'message': 'File is not valid UTF-8 text'})
                return

            lines = [line for line in text.strip().split('\n') if line.strip()]
            if len(lines) < 2:
                self._send_json(400, {'error': True, 'message': 'CSV must have a header and at least one data row'})
                return

            # Auto-detect column with emails/handles, fix header, strip to single column
            import csv as _csv
            import io as _io

            header_cols = [c.strip().lower().replace('"', '').replace("'", "") for c in lines[0].split(',')]
            multi_column = len(header_cols) > 1
            valid_headers = ('email', 'handle', 'emails', 'handles')
            header_fixed = False
            columns_stripped = False

            # Find the best column: scan all columns for emails/handles
            best_col_idx = 0
            detected_type = 'handle'

            if multi_column:
                # Try to find a column with a valid header name first
                for i, col_name in enumerate(header_cols):
                    if col_name in valid_headers:
                        best_col_idx = i
                        detected_type = 'email' if col_name in ('email', 'emails') else 'handle'
                        break
                else:
                    # No valid header found — scan ALL columns to find the best one
                    best_email_score = -1
                    for col_idx in range(len(header_cols)):
                        sample_values = []
                        for row in lines[1:6]:
                            cols = row.split(',')
                            if col_idx < len(cols):
                                val = cols[col_idx].strip().replace('"', '').replace("'", "")
                                if val:
                                    sample_values.append(val)
                        if not sample_values:
                            continue
                        email_count = sum(1 for v in sample_values if '@' in v and '.' in v.split('@')[-1])
                        email_ratio = email_count / len(sample_values)
                        if email_ratio > 0.5 and email_count > best_email_score:
                            best_email_score = email_count
                            best_col_idx = col_idx
                            detected_type = 'email'

                    # If no email column found, default to column 0 as handles
                    if best_email_score < 0:
                        best_col_idx = 0
                        detected_type = 'handle'

                # Extract only the best column into a single-column CSV
                reader = _csv.reader(_io.StringIO('\n'.join(lines)))
                new_lines = [detected_type]  # header
                for i, row in enumerate(reader):
                    if i == 0:
                        continue  # skip original header
                    if best_col_idx < len(row):
                        val = row[best_col_idx].strip()
                        if val:
                            new_lines.append(val)

                lines = new_lines
                body = '\n'.join(lines).encode('utf-8')
                columns_stripped = True
                header_fixed = True
                _log(f"Stripped to single column (col {best_col_idx}), header set to '{detected_type}'")

            else:
                # Single column — just fix the header if needed
                first_col = header_cols[0] if header_cols else ''
                if first_col not in valid_headers:
                    sample_values = []
                    for row in lines[1:6]:
                        val = row.strip().replace('"', '').replace("'", "")
                        if val:
                            sample_values.append(val)

                    if not sample_values:
                        self._send_json(400, {'error': True, 'message': 'CSV has no data rows'})
                        return

                    email_count = sum(1 for v in sample_values if '@' in v and '.' in v.split('@')[-1])
                    detected_type = 'email' if email_count > len(sample_values) / 2 else 'handle'

                    lines[0] = detected_type
                    body = '\n'.join(lines).encode('utf-8')
                    header_fixed = True
                    _log(f"Auto-fixed header: '{first_col}' -> '{detected_type}'")

            row_count = len(lines) - 1

            # Save file to imports directory
            imports = Path(IMPORTS_DIR)
            imports.mkdir(parents=True, exist_ok=True)

            save_path = imports / filename
            if save_path.exists():
                stem = save_path.stem
                ts = int(time.time())
                filename = f"{stem}_{ts}.csv"
                save_path = imports / filename

            save_path.write_bytes(body)
            _log(f"Saved {filename} ({row_count} rows, {content_length} bytes)")

            import_host_dir = os.environ.get('IMPORT_HOST_DIR', '')
            host_path = os.path.join(import_host_dir, filename) if import_host_dir else filename

            resp = {
                'success': True,
                'filename': filename,
                'rows': row_count,
                'size_bytes': content_length,
                'host_path': host_path,
                'message': f'Uploaded {filename} with {row_count} rows',
            }
            if header_fixed:
                resp['header_fixed'] = True
                resp['detected_type'] = detected_type
                resp['message'] += f' (auto-detected as {detected_type}s)'
            if columns_stripped:
                resp['columns_stripped'] = True
                resp['message'] += f' (extracted {detected_type} column from multi-column CSV)'
            self._send_json(200, resp)

        except Exception as e:
            _log(f"Upload error: {e}")
            self._send_json(500, {'error': True, 'message': str(e)})

    # ── Utilities ──

    def _send_json(self, code: int, data: dict):
        body = json.dumps(data).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self._cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def _cors_headers(self):
        # No CORS headers needed — upload page and API are same-origin
        pass

    def log_message(self, format, *args):
        _log(format % args)


# ─── Server start ──────────────────────────────────────────────────────

def start_upload_server() -> HTTPServer | None:
    """Start the upload server in a daemon thread. Returns the server instance."""
    try:
        # UPLOAD_BIND defaults to 127.0.0.1 (localhost only) for safety.
        # Inside Docker, set UPLOAD_BIND=0.0.0.0 — host access is restricted by Docker's -p 127.0.0.1:port:port.
        server = HTTPServer((UPLOAD_BIND, UPLOAD_PORT), UploadHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True, name='upload-server')
        thread.start()
        _log(f"File upload server running on http://{UPLOAD_BIND}:{UPLOAD_PORT}")
        return server
    except OSError as e:
        _log(f"Could not start upload server on port {UPLOAD_PORT}: {e}")
        return None
