import os
import sys
import json
import uuid
import subprocess
import sqlite3
from flask import (
    Flask, request, redirect, send_file,
    render_template_string, jsonify, send_from_directory, session
)

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app.secret_key = 'geotrace-session-key-2024'

UPLOAD_FOLDER = os.path.join(BASE_DIR, "member1", "images")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


def clear_session_data():
    """Wipe uploads + generated outputs for a fresh session."""
    # Clear uploaded images
    if os.path.exists(UPLOAD_FOLDER):
        for f in os.listdir(UPLOAD_FOLDER):
            fp = os.path.join(UPLOAD_FOLDER, f)
            if os.path.isfile(fp):
                try:
                    os.remove(fp)
                except Exception:
                    pass
    # Clear generated pipeline outputs
    for rel in [
        ("member1", "output_data.json"),
        ("member1", "metadata.db"),
        ("member2", "clusters.json"),
        ("member2", "points_with_clusters.json"),
        ("member3", "intelligence.json"),
        ("member4", "dashboard.html"),
        ("member4", "map.html"),
    ]:
        p = os.path.join(BASE_DIR, *rel)
        if os.path.exists(p):
            try:
                os.remove(p)
            except Exception:
                pass
    print("[SESSION] Cleared all data for new session")


@app.route("/api/new-session", methods=["POST"])
def new_session():
    """Called by the browser when sessionStorage is empty (= new session)."""
    clear_session_data()
    return jsonify({"success": True})


# ═══════════════════════════════════════════
#  TEMPLATES
# ═══════════════════════════════════════════

ERROR_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>GeoTrace — Error</title>
    <meta charset="utf-8">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            background: #0d0d0d;
            color: #e0e0e0;
            font-family: 'Segoe UI', sans-serif;
            height: 100vh;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            text-align: center;
            padding: 24px;
        }
        .icon { font-size: 56px; margin-bottom: 24px; }
        .title {
            font-size: 22px;
            color: #ff4444;
            margin-bottom: 12px;
            font-weight: bold;
        }
        .detail {
            font-size: 14px;
            color: #666;
            max-width: 480px;
            line-height: 1.6;
            margin-bottom: 32px;
        }
        .back-btn {
            background: #00ffcc;
            color: #000;
            border: none;
            padding: 12px 28px;
            border-radius: 10px;
            font-size: 14px;
            font-weight: bold;
            cursor: pointer;
            text-decoration: none;
        }
        .back-btn:hover { opacity: 0.85; }
        .tip {
            margin-top: 24px;
            font-size: 12px;
            color: #444;
            max-width: 440px;
            line-height: 1.6;
            border: 1px solid #222;
            border-radius: 8px;
            padding: 12px 16px;
            background: #111;
        }
        .tip b { color: #00ffcc; }
    </style>
</head>
<body>
    <div class="icon">📍</div>
    <div class="title">{{ error_title }}</div>
    <div class="detail">{{ error_detail }}</div>
    <a href="/" class="back-btn">← Back to Upload</a>
    <div class="tip">
        <b>Tip:</b> GPS coordinates are embedded by your camera app automatically.
        Avoid WhatsApp, Instagram, or screenshot images — they strip this data.
        Use original photos from your phone's gallery.
    </div>
</body>
</html>
"""

UPLOAD_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>GeoTrace — Upload Photos</title>
    <meta charset="utf-8">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            background: #0d0d0d;
            color: #e0e0e0;
            font-family: 'Segoe UI', sans-serif;
            min-height: 100vh;
            display: flex;
            flex-direction: column;
            align-items: center;
            padding: 48px 24px;
        }

        .logo {
            font-size: 32px;
            font-weight: bold;
            color: #00ffcc;
            margin-bottom: 8px;
            letter-spacing: 2px;
        }
        .tagline {
            font-size: 13px;
            color: #555;
            margin-bottom: 36px;
            letter-spacing: 1px;
        }

        /* ── Gallery ── */
        .gallery-section {
            width: 560px;
            margin-bottom: 24px;
            display: none;
            animation: fadeIn 0.3s ease;
        }
        @keyframes fadeIn { from { opacity: 0; transform: translateY(-8px); } to { opacity: 1; transform: translateY(0); } }
        .section-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 12px;
        }
        .section-title {
            font-size: 12px;
            color: #888;
            letter-spacing: 1px;
            text-transform: uppercase;
        }
        .clear-btn {
            background: transparent;
            border: 1px solid #ff4444;
            color: #ff4444;
            padding: 4px 14px;
            border-radius: 6px;
            font-size: 11px;
            cursor: pointer;
            transition: all 0.2s;
        }
        .clear-btn:hover { background: #ff4444; color: #fff; }
        .gallery {
            display: flex;
            flex-wrap: wrap;
            gap: 10px;
        }
        .gallery-item {
            position: relative;
            width: 76px;
            border-radius: 8px;
            overflow: hidden;
            border: 1px solid #333;
            background: #1a1a1a;
            transition: border-color 0.2s, transform 0.2s;
        }
        .gallery-item:hover { border-color: #00ffcc; transform: scale(1.05); }
        .gallery-item img {
            width: 76px;
            height: 76px;
            object-fit: cover;
            display: block;
        }
        .gallery-name {
            font-size: 8px;
            padding: 3px 4px;
            color: #666;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
            text-align: center;
        }
        .del-btn {
            position: absolute;
            top: 3px;
            right: 3px;
            background: rgba(255,68,68,0.9);
            color: #fff;
            border: none;
            border-radius: 50%;
            width: 20px;
            height: 20px;
            font-size: 11px;
            cursor: pointer;
            line-height: 20px;
            text-align: center;
            display: none;
            transition: background 0.2s;
        }
        .del-btn:hover { background: #ff0000; }
        .gallery-item:hover .del-btn { display: block; }

        /* ── Upload box ── */
        .upload-box {
            width: 560px;
            border: 2px dashed #333;
            border-radius: 16px;
            padding: 40px 32px;
            text-align: center;
            background: #111;
            transition: border-color 0.2s;
            cursor: pointer;
            position: relative;
        }
        .upload-box.dragover {
            border-color: #00ffcc;
            background: #0a1f1a;
        }
        .upload-icon { font-size: 40px; margin-bottom: 12px; }
        .upload-title { font-size: 17px; color: #fff; margin-bottom: 6px; }
        .upload-sub { font-size: 12px; color: #555; margin-bottom: 20px; }
        #file-input { display: none; }
        .browse-btn {
            background: #1a1a1a;
            border: 1px solid #333;
            color: #00ffcc;
            padding: 8px 20px;
            border-radius: 8px;
            font-size: 13px;
            cursor: pointer;
            letter-spacing: 0.5px;
            transition: border-color 0.2s;
        }
        .browse-btn:hover { border-color: #00ffcc; }
        .file-list {
            margin-top: 16px;
            text-align: left;
            max-height: 120px;
            overflow-y: auto;
        }
        .file-item {
            font-size: 12px;
            color: #888;
            padding: 4px 0;
            border-bottom: 1px solid #1a1a1a;
            display: flex;
            align-items: center;
            gap: 8px;
        }
        .file-item span { color: #00ffcc; }

        /* ── Track button ── */
        .track-btn {
            margin-top: 20px;
            width: 560px;
            padding: 16px;
            background: #00ffcc;
            color: #000;
            border: none;
            border-radius: 12px;
            font-size: 16px;
            font-weight: bold;
            cursor: pointer;
            letter-spacing: 1px;
            transition: opacity 0.2s;
        }
        .track-btn:disabled { opacity: 0.3; cursor: not-allowed; }
        .track-btn:hover:not(:disabled) { opacity: 0.85; }

        /* ── Dashboard link ── */
        .dashboard-link {
            margin-top: 16px;
            font-size: 13px;
            color: #555;
            display: none;
        }
        .dashboard-link a {
            color: #00ffcc;
            text-decoration: none;
        }
        .dashboard-link a:hover { text-decoration: underline; }

        /* ── Loading ── */
        .loading {
            display: none;
            margin-top: 24px;
            text-align: center;
        }
        .loading-text {
            font-size: 14px;
            color: #00ffcc;
            letter-spacing: 1px;
        }
        .spinner {
            width: 32px;
            height: 32px;
            border: 3px solid #222;
            border-top: 3px solid #00ffcc;
            border-radius: 50%;
            animation: spin 0.8s linear infinite;
            margin: 12px auto 0;
        }
        @keyframes spin { to { transform: rotate(360deg); } }
        .steps { margin-top: 12px; font-size: 12px; color: #555; }
        .steps span {
            display: block;
            padding: 2px 0;
            transition: color 0.3s;
        }
        .steps span.active { color: #00ffcc; }

        /* ── Modern Modal ── */
        .modal-overlay {
            position: fixed; top: 0; left: 0; right: 0; bottom: 0;
            background: rgba(0, 0, 0, 0.8);
            backdrop-filter: blur(4px);
            display: flex; align-items: center; justify-content: center;
            opacity: 0; pointer-events: none;
            transition: opacity 0.2s ease;
            z-index: 9999;
        }
        .modal-overlay.show { opacity: 1; pointer-events: auto; }
        .modal-box {
            background: #111;
            border: 1px solid #333;
            border-radius: 12px;
            padding: 24px;
            width: 320px;
            text-align: center;
            transform: scale(0.9);
            transition: transform 0.2s ease;
            box-shadow: 0 10px 30px rgba(0,0,0,0.5);
        }
        .modal-overlay.show .modal-box { transform: scale(1); }
        .modal-title { font-size: 16px; color: #fff; margin-bottom: 8px; font-weight: bold; }
        .modal-msg { font-size: 13px; color: #aaa; margin-bottom: 24px; line-height: 1.5; }
        .modal-btns { display: flex; gap: 12px; justify-content: center; }
        .modal-btn {
            padding: 8px 16px; border-radius: 6px; font-size: 13px; font-weight: bold;
            cursor: pointer; border: none; transition: opacity 0.2s;
        }
        .modal-btn:hover { opacity: 0.85; }
        .modal-btn.cancel { background: #222; color: #ccc; border: 1px solid #444; }
        .modal-btn.danger { background: #ff4444; color: #fff; }
        .modal-btn.primary { background: #00ffcc; color: #000; }
    </style>
</head>
<body>

    <div class="logo">🌍 GeoTrace</div>
    <div class="tagline">Upload photos — we map the story hidden inside them</div>

    <!-- ── Existing Images Gallery ── -->
    <div class="gallery-section" id="gallery-section">
        <div class="section-header">
            <span class="section-title">📁 Your Photos (<span id="gallery-count">0</span>)</span>
            <button class="clear-btn" onclick="clearAll()">Clear All</button>
        </div>
        <div class="gallery" id="gallery"></div>
    </div>

    <!-- ── Upload Form ── -->
    <form id="upload-form" action="/track" method="POST" enctype="multipart/form-data">
        <div class="upload-box" id="drop-zone">
            <div class="upload-icon">📸</div>
            <div class="upload-title">Add more photos</div>
            <div class="upload-sub">Supports JPG, JPEG, PNG with GPS metadata</div>
            <button type="button" class="browse-btn"
                onclick="document.getElementById('file-input').click()">
                Browse Files
            </button>
            <input type="file" id="file-input" name="images"
                   multiple accept=".jpg,.jpeg,.png">
            <div class="file-list" id="file-list"></div>
        </div>

        <button type="submit" class="track-btn" id="track-btn" disabled>
            Track Movement →
        </button>
    </form>

    <!-- ── Previous Dashboard Link ── -->
    <div class="dashboard-link" id="dashboard-link">
        <a href="/dashboard">📊 View Previous Dashboard</a>
    </div>

    <!-- ── Loading ── -->
    <div class="loading" id="loading">
        <div class="spinner"></div>
        <div class="loading-text" style="margin-top:16px">
            Analyzing your photos...
        </div>
        <div class="steps" id="steps">
            <span id="s1">⏳ Extracting GPS metadata...</span>
            <span id="s2">⏳ Clustering locations...</span>
            <span id="s3">⏳ Analyzing movement patterns...</span>
            <span id="s4">⏳ Building intelligence map...</span>
        </div>
    </div>

    <!-- ── Modern Modal HTML ── -->
    <div class="modal-overlay" id="custom-modal">
        <div class="modal-box">
            <div class="modal-title" id="modal-title">Notice</div>
            <div class="modal-msg" id="modal-msg"></div>
            <div class="modal-btns" id="modal-btns"></div>
        </div>
    </div>

    <script>
        const dropZone   = document.getElementById('drop-zone');
        const fileInput  = document.getElementById('file-input');
        const fileList   = document.getElementById('file-list');
        const trackBtn   = document.getElementById('track-btn');
        const form       = document.getElementById('upload-form');
        const loading    = document.getElementById('loading');
        const gSection   = document.getElementById('gallery-section');
        const gGallery   = document.getElementById('gallery');
        const gCount     = document.getElementById('gallery-count');
        const dashLink   = document.getElementById('dashboard-link');

        let selectedFiles = [];
        let existingCount = 0;

        /* ── Load existing images ── */
        function loadGallery() {
            fetch('/api/images').then(r => r.json()).then(images => {
                existingCount = images.length;
                if (images.length > 0) {
                    gSection.style.display = 'block';
                    gCount.textContent = images.length;
                    gGallery.innerHTML = '';
                    images.forEach(img => {
                        const div = document.createElement('div');
                        div.className = 'gallery-item';
                        div.innerHTML = `
                            <img src="/uploads/${encodeURIComponent(img.filename)}"
                                 alt="${img.filename}" loading="lazy">
                            <div class="gallery-name" title="${img.filename}">${img.filename}</div>
                            <button class="del-btn"
                                onclick="event.stopPropagation(); deleteImage('${img.filename.replace(/'/g, "\\'")}')"
                                title="Remove">✕</button>
                        `;
                        gGallery.appendChild(div);
                    });
                } else {
                    gSection.style.display = 'none';
                }
                updateBtn();
            });
        }

        function deleteImage(filename) {
            fetch('/api/delete/' + encodeURIComponent(filename), { method: 'POST' })
                .then(r => r.json())
                .then(() => loadGallery());
        }

        /* ── Custom Modal Functions ── */
        const modalOverlay = document.getElementById('custom-modal');
        const modalTitle   = document.getElementById('modal-title');
        const modalMsg     = document.getElementById('modal-msg');
        const modalBtns    = document.getElementById('modal-btns');

        function showCustomAlert(msg, title = 'Notice') {
            modalTitle.textContent = title;
            modalMsg.textContent = msg;
            modalBtns.innerHTML = `<button class="modal-btn primary" onclick="closeModal()">OK</button>`;
            modalOverlay.classList.add('show');
        }

        function showCustomConfirm(msg, title = 'Confirm', onConfirm) {
            modalTitle.textContent = title;
            modalMsg.textContent = msg;
            modalBtns.innerHTML = `
                <button class="modal-btn cancel" onclick="closeModal()">Cancel</button>
                <button class="modal-btn danger" id="modal-confirm-btn">Delete</button>
            `;
            document.getElementById('modal-confirm-btn').onclick = () => {
                closeModal();
                if (onConfirm) onConfirm();
            };
            modalOverlay.classList.add('show');
        }

        function closeModal() {
            modalOverlay.classList.remove('show');
        }

        function clearAll() {
            showCustomConfirm('Are you sure you want to remove all uploaded photos?', 'Clear All Photos', () => {
                fetch('/api/clear', { method: 'POST' }).then(() => loadGallery());
            });
        }

        /* ── Check if previous dashboard exists ── */
        fetch('/api/has-dashboard').then(r => r.json()).then(d => {
            if (d.exists) dashLink.style.display = 'block';
        });

        /* ── Drag & Drop ── */
        dropZone.addEventListener('dragover', e => {
            e.preventDefault();
            dropZone.classList.add('dragover');
        });
        dropZone.addEventListener('dragleave', () => {
            dropZone.classList.remove('dragover');
        });
        dropZone.addEventListener('drop', e => {
            e.preventDefault();
            dropZone.classList.remove('dragover');
            const files = Array.from(e.dataTransfer.files).filter(
                f => f.name.match(/\\.(jpg|jpeg|png)$/i)
            );
            addFiles(files);
        });

        /* ── Browse ── */
        fileInput.addEventListener('change', () => {
            addFiles(Array.from(fileInput.files));
        });

        function addFiles(files) {
            selectedFiles = [...selectedFiles, ...files];
            renderFileList();
        }

        function renderFileList() {
            fileList.innerHTML = '';
            selectedFiles.forEach(f => {
                const div = document.createElement('div');
                div.className = 'file-item';
                div.innerHTML = `<span>📷</span> ${f.name}
                    <span style="margin-left:auto;color:#555">
                        ${(f.size/1024).toFixed(1)} KB
                    </span>`;
                fileList.appendChild(div);
            });
            updateBtn();
        }

        function updateBtn() {
            const total = existingCount + selectedFiles.length;
            trackBtn.disabled = total === 0;
            if (selectedFiles.length > 0) {
                trackBtn.textContent = `Track ${total} Photo${total > 1 ? 's' : ''} →`;
            } else if (existingCount > 0) {
                trackBtn.textContent = `Re-analyze ${existingCount} Photo${existingCount > 1 ? 's' : ''} →`;
            } else {
                trackBtn.textContent = 'Track Movement →';
            }
        }

        /* ── Submit ── */
        form.addEventListener('submit', e => {
            e.preventDefault();

            const total = existingCount + selectedFiles.length;
            if (total === 0) return;

            const formData = new FormData();
            selectedFiles.forEach(f => formData.append('images', f));

            // Show loading
            form.style.display  = 'none';
            gSection.style.display = 'none';
            dashLink.style.display = 'none';
            loading.style.display = 'block';

            // Animate steps
            const steps = ['s1','s2','s3','s4'];
            let i = 0;
            const interval = setInterval(() => {
                if (i < steps.length) {
                    document.getElementById(steps[i]).classList.add('active');
                    document.getElementById(steps[i]).textContent =
                        document.getElementById(steps[i]).textContent.replace('⏳','✅');
                    i++;
                } else {
                    clearInterval(interval);
                }
            }, 2500);

            // POST
            fetch('/track', {
                method: 'POST',
                body: formData
            }).then(res => {
                return res.text().then(html => {
                    document.open();
                    document.write(html);
                    document.close();
                });
            }).catch(err => {
                showCustomAlert('Error: ' + err, 'Upload Failed');
                setTimeout(() => location.reload(), 2000);
            });
        });

        /* ── Init: check if this is a new browser session ── */
        (async function initSession() {
            if (!sessionStorage.getItem('geotrace_active')) {
                // New session — clear all old data
                await fetch('/api/new-session', { method: 'POST' });
                sessionStorage.setItem('geotrace_active', '1');
            }
            loadGallery();
        })();
    </script>

</body>
</html>
"""

RESULTS_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>GeoTrace — Results</title>
    <meta charset="utf-8">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            background: #0d0d0d;
            color: #e0e0e0;
            font-family: 'Segoe UI', sans-serif;
            min-height: 100vh;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            padding: 40px 24px;
        }
        .card {
            background: #111;
            border: 1px solid #222;
            border-radius: 16px;
            padding: 36px;
            max-width: 520px;
            width: 100%;
            animation: fadeUp 0.4s ease;
        }
        @keyframes fadeUp {
            from { opacity: 0; transform: translateY(16px); }
            to   { opacity: 1; transform: translateY(0); }
        }
        .card-title {
            font-size: 22px;
            color: #00ffcc;
            margin-bottom: 6px;
            font-weight: bold;
        }
        .card-sub {
            font-size: 13px;
            color: #666;
            margin-bottom: 24px;
        }
        .stat-row {
            display: flex;
            gap: 12px;
            margin-bottom: 24px;
        }
        .stat {
            flex: 1;
            background: #1a1a1a;
            border: 1px solid #2a2a2a;
            border-radius: 10px;
            padding: 14px;
            text-align: center;
        }
        .stat-num {
            font-size: 28px;
            font-weight: bold;
            color: #00ffcc;
        }
        .stat-num.red { color: #ff4444; }
        .stat-label {
            font-size: 10px;
            color: #888;
            text-transform: uppercase;
            margin-top: 4px;
            letter-spacing: 1px;
        }
        .photo-list {
            max-height: 220px;
            overflow-y: auto;
            margin-bottom: 24px;
            border: 1px solid #222;
            border-radius: 8px;
            background: #0d0d0d;
        }
        .photo-item {
            display: flex;
            align-items: center;
            gap: 10px;
            padding: 8px 12px;
            border-bottom: 1px solid #1a1a1a;
            font-size: 13px;
        }
        .photo-item:last-child { border-bottom: none; }
        .photo-item .icon { font-size: 16px; flex-shrink: 0; }
        .photo-item .name {
            color: #ccc;
            flex: 1;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }
        .badge {
            font-size: 10px;
            padding: 2px 8px;
            border-radius: 4px;
            font-weight: 600;
            letter-spacing: 0.5px;
            flex-shrink: 0;
        }
        .badge.ok  { background: #0a2a1a; color: #00ffcc; }
        .badge.fail { background: #2a0a0a; color: #ff4444; }
        .btn-row {
            display: flex;
            gap: 12px;
        }
        .btn {
            flex: 1;
            padding: 14px;
            border-radius: 10px;
            font-size: 14px;
            font-weight: bold;
            cursor: pointer;
            text-align: center;
            text-decoration: none;
            border: none;
            transition: opacity 0.2s;
        }
        .btn:hover { opacity: 0.85; }
        .btn-primary { background: #00ffcc; color: #000; }
        .btn-secondary { background: #1a1a1a; color: #00ffcc; border: 1px solid #333; }
    </style>
</head>
<body>
    <div class="card">
        <div class="card-title">📊 Analysis Complete</div>
        <div class="card-sub">{{ total }} photo{{ 's' if total != 1 else '' }} processed</div>

        <div class="stat-row">
            <div class="stat">
                <div class="stat-num">{{ gps_found }}</div>
                <div class="stat-label">GPS Found</div>
            </div>
            <div class="stat">
                <div class="stat-num red">{{ no_gps }}</div>
                <div class="stat-label">No GPS</div>
            </div>
        </div>

        <div class="photo-list">
            {% for img in results %}
            <div class="photo-item">
                <span class="icon">{{ '✅' if img.has_gps else '❌' }}</span>
                <span class="name" title="{{ img.filename }}">{{ img.filename }}</span>
                <span class="badge {{ 'ok' if img.has_gps else 'fail' }}">
                    {{ 'GPS Found' if img.has_gps else 'No GPS' }}
                </span>
            </div>
            {% endfor %}
        </div>

        {% if has_dashboard %}
        <div class="btn-row">
            <a href="/" class="btn btn-secondary">← Upload More</a>
            <a href="/dashboard" class="btn btn-primary">View Dashboard →</a>
        </div>
        {% else %}
        <div class="btn-row">
            <a href="/" class="btn btn-primary" style="flex:1;">← Upload Different Photos</a>
        </div>
        {% endif %}
    </div>
</body>
</html>
"""


# ═══════════════════════════════════════════
#  API ROUTES
# ═══════════════════════════════════════════

@app.route("/api/images")
def api_images():
    """Return list of currently uploaded images."""
    images = []
    if os.path.exists(UPLOAD_FOLDER):
        for f in sorted(os.listdir(UPLOAD_FOLDER)):
            if f.lower().endswith(('.jpg', '.jpeg', '.png')):
                size = os.path.getsize(os.path.join(UPLOAD_FOLDER, f))
                images.append({"filename": f, "size": size})
    return jsonify(images)


@app.route("/uploads/<filename>")
def serve_upload(filename):
    """Serve an uploaded image (for thumbnails)."""
    safe = os.path.basename(filename)
    return send_from_directory(UPLOAD_FOLDER, safe)


@app.route("/api/delete/<filename>", methods=["POST"])
def delete_image(filename):
    """Delete a single uploaded image."""
    safe = os.path.basename(filename)
    path = os.path.join(UPLOAD_FOLDER, safe)
    if os.path.exists(path):
        os.remove(path)
        return jsonify({"success": True})
    return jsonify({"success": False, "error": "Not found"}), 404


@app.route("/api/clear", methods=["POST"])
def clear_all():
    """Delete all uploaded images."""
    if os.path.exists(UPLOAD_FOLDER):
        for f in os.listdir(UPLOAD_FOLDER):
            fp = os.path.join(UPLOAD_FOLDER, f)
            if os.path.isfile(fp):
                try:
                    os.remove(fp)
                except Exception:
                    pass
    return jsonify({"success": True})


@app.route("/api/has-dashboard")
def has_dashboard():
    """Check if a dashboard has been previously generated."""
    path = os.path.join(BASE_DIR, "member4", "dashboard.html")
    return jsonify({"exists": os.path.exists(path)})


# ═══════════════════════════════════════════
#  PAGE ROUTES
# ═══════════════════════════════════════════

@app.route("/")
def index():
    return render_template_string(UPLOAD_HTML)


@app.route("/track", methods=["POST"])
def track():
    # ── Step 1: Save NEW uploaded images (ADD to existing) ──
    files = request.files.getlist("images")
    new_count = 0
    for file in files:
        if file.filename:
            safe = os.path.basename(file.filename)
            file.save(os.path.join(UPLOAD_FOLDER, safe))
            new_count += 1

    if new_count:
        print(f"[UPLOAD] Added {new_count} new image(s)")

    # ── Collect all images currently in the folder ──
    all_images = sorted([
        f for f in os.listdir(UPLOAD_FOLDER)
        if f.lower().endswith(('.jpg', '.jpeg', '.png'))
    ])

    if not all_images:
        return render_template_string(ERROR_HTML,
            error_title="No images found",
            error_detail="Please upload some photos first."
        ), 400

    print(f"[PIPELINE] Processing {len(all_images)} total images")

    # ── Step 2: Clear database for fresh processing ──
    db_path = os.path.join(BASE_DIR, "member1", "metadata.db")
    if os.path.exists(db_path):
        try:
            conn = sqlite3.connect(db_path)
            conn.execute("DELETE FROM images")
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"[DB] Warning: {e}")

    # ── Pipeline directories ──
    member1_dir = os.path.join(BASE_DIR, "member1")
    member2_dir = os.path.join(BASE_DIR, "member2")
    member3_dir = os.path.join(BASE_DIR, "member3")
    member4_dir = os.path.join(BASE_DIR, "member4")

    try:
        # ── Step 3: Member 1 — EXIF extraction ──
        print("[PIPELINE] Running Member 1: EXIF extraction...")
        result = subprocess.run(
            [sys.executable, "main.py"],
            cwd=member1_dir,
            capture_output=True, text=True
        )
        print(result.stdout)
        if result.returncode != 0:
            print(f"[ERROR] Member 1:\n{result.stderr}")
            return render_template_string(ERROR_HTML,
                error_title="EXIF extraction failed",
                error_detail=result.stderr[:300]
            ), 500

        # ── Check which images had GPS ──
        output_json = os.path.join(member1_dir, "output_data.json")
        gps_images = set()
        if os.path.exists(output_json):
            with open(output_json, "r") as f:
                extracted = json.load(f)
            gps_images = {item["image_id"] for item in extracted}

        # Build per-image results (filename only — no paths)
        results = []
        for img in all_images:
            results.append({
                "filename": img,
                "has_gps": img in gps_images
            })

        gps_found = len(gps_images)
        no_gps = len(all_images) - gps_found
        print(f"[PIPELINE] GPS found: {gps_found}, No GPS: {no_gps}")

        if gps_found == 0:
            return render_template_string(RESULTS_HTML,
                total=len(all_images), gps_found=0,
                no_gps=len(all_images), results=results,
                has_dashboard=False
            )

        # ── Step 4: Member 2 — Clustering ──
        print("[PIPELINE] Running Member 2: Clustering...")
        result = subprocess.run(
            [sys.executable, "cluster.py"],
            cwd=member2_dir,
            capture_output=True, text=True
        )
        print(result.stdout)
        if result.returncode != 0:
            print(f"[ERROR] Member 2:\n{result.stderr}")
            return render_template_string(ERROR_HTML,
                error_title="Clustering failed",
                error_detail=result.stderr[:300]
            ), 500

        # ── Step 5: Member 3 — Movement analysis ──
        print("[PIPELINE] Running Member 3: Movement analysis...")
        result = subprocess.run(
            [sys.executable, "member3_movement.py"],
            cwd=member3_dir,
            capture_output=True, text=True
        )
        print(result.stdout)
        if result.returncode != 0:
            print(f"[ERROR] Member 3:\n{result.stderr}")
            return render_template_string(ERROR_HTML,
                error_title="Movement analysis failed",
                error_detail=result.stderr[:300]
            ), 500

        # ── Step 6: Member 4 — Dashboard generation ──
        print("[PIPELINE] Running Member 4: Dashboard generation...")
        result = subprocess.run(
            [sys.executable, "member4_dashboard.py"],
            cwd=member4_dir,
            capture_output=True, text=True
        )
        print(result.stdout)
        if result.returncode != 0:
            print(f"[ERROR] Member 4:\n{result.stderr}")
            return render_template_string(ERROR_HTML,
                error_title="Dashboard generation failed",
                error_detail=result.stderr[:300]
            ), 500

        print("[PIPELINE] ✅ All steps complete")

    except Exception as e:
        print(f"[FATAL] Pipeline crashed: {e}")
        return render_template_string(ERROR_HTML,
            error_title="Unexpected error",
            error_detail=str(e)[:300]
        ), 500

    # ── Show results page with per-image GPS status ──
    return render_template_string(RESULTS_HTML,
        total=len(all_images), gps_found=gps_found,
        no_gps=no_gps, results=results,
        has_dashboard=True
    )


@app.route("/dashboard")
def dashboard():
    dashboard_path = os.path.join(BASE_DIR, "member4", "dashboard.html")
    if not os.path.exists(dashboard_path):
        return redirect("/")

    # Inject a "Back to Upload" button into the dashboard
    with open(dashboard_path, "r", encoding="utf-8") as f:
        html = f.read()

    back_btn = """<a href="/" style="
        position: fixed;
        top: 14px;
        right: 24px;
        z-index: 9999;
        background: #00ffcc;
        color: #000;
        padding: 8px 18px;
        border-radius: 8px;
        text-decoration: none;
        font-weight: bold;
        font-size: 13px;
        font-family: 'Segoe UI', sans-serif;
        box-shadow: 0 2px 12px rgba(0,255,204,0.3);
        transition: opacity 0.2s;
    " onmouseover="this.style.opacity='0.85'"
       onmouseout="this.style.opacity='1'">
        ← Upload More
    </a>"""

    html = html.replace("<body>", f"<body>{back_btn}", 1)
    return html


@app.route("/map.html")
def map_file():
    map_path = os.path.join(BASE_DIR, "member4", "map.html")
    if os.path.exists(map_path):
        return send_file(map_path)
    return "Map not generated yet", 404


# ═══════════════════════════════════════════
#  RUN
# ═══════════════════════════════════════════
if __name__ == "__main__":
    app.run(debug=True, port=5000)