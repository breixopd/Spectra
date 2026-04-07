// manual-tools.js — Orchestrator
// Sub-modules loaded before this: tools.js, terminal.js, checklist.js, results.js

// === Tips System ===
const TIPS = [
    "Start with <b>Nmap</b> to discover open ports and services, then use the findings to target specific tools.",
    "After a port scan, use <b>SearchSploit</b> to find known exploits for discovered service versions.",
    "For web targets, run <b>WhatWeb</b> first to identify technologies, then <b>Nikto</b> or <b>Nuclei</b> for vulnerabilities.",
    "Use the <b>CVE Lookup</b> tab to search for known vulnerabilities by product name and version.",
    "The <b>Pipeline</b> tab lets you chain tools together. Use templates for common workflows.",
    "Click the action buttons on findings (hover to reveal) to quickly run follow-up tools.",
    "Create a <b>Session</b> to track all your findings, actions, and notes for reporting.",
    "For brute-force testing, manage wordlists in <b>Settings</b> and tools will auto-configure.",
    "Use <b>Nuclei</b> for comprehensive vulnerability scanning — it checks thousands of templates.",
    "The <b>{prev}</b> placeholder in pipelines passes the previous tool's output as the next tool's target.",
];
let tipIndex = Math.floor(Math.random() * TIPS.length);

function showTip() {
    document.getElementById('tip-text').innerHTML = TIPS[tipIndex % TIPS.length];
}
function nextTip() {
    tipIndex++;
    showTip();
}


// === Helper Sub-Tab Switching ===
let activeHelperTab = 'revshell';
function switchHelperTab(tab) {
    activeHelperTab = tab;
    document.querySelectorAll('.helper-tab-btn').forEach(b => {
        const isActive = b.onclick && b.onclick.toString().includes("'" + tab + "'");
        if (isActive) {
            b.className = 'helper-tab-btn active px-3 py-2 text-xs font-medium text-violet-400 border-b-2 border-violet-500 whitespace-nowrap';
        } else {
            b.className = 'helper-tab-btn px-3 py-2 text-xs font-medium text-slate-400 border-b-2 border-transparent hover:text-white whitespace-nowrap';
        }
    });
    document.querySelectorAll('.helper-panel').forEach(p => p.classList.add('hidden'));
    const panel = document.getElementById('helper-' + tab);
    if (panel) panel.classList.remove('hidden');
}


// === Reverse Shell Generator ===
let activeShellCategory = 'all';
let selectedShellIdx = null;

function initRevShells() {
    const filterContainer = document.getElementById('revshell-cat-filters');
    filterContainer.innerHTML = SHELL_CATEGORIES.map(c =>
        `<button onclick="filterShells('${c.id}')" class="revshell-cat-btn px-2 py-1 rounded text-[11px] transition-colors ${
            c.id === 'all' ? 'bg-violet-600 text-white' : 'bg-slate-800 text-slate-300 hover:bg-violet-500/10 border border-white/5'
        }" data-cat="${c.id}">${c.label}</button>`
    ).join('');
    filterShells('all');
}

function filterShells(cat) {
    activeShellCategory = cat;
    document.querySelectorAll('.revshell-cat-btn').forEach(b => {
        const isActive = b.dataset.cat === cat;
        b.className = `revshell-cat-btn px-2 py-1 rounded text-[11px] transition-colors ${isActive ? 'bg-violet-600 text-white' : 'bg-slate-800 text-slate-300 hover:bg-violet-500/10 border border-white/5'}`;
    });
    renderShellList();
}

function renderShellList() {
    const shells = activeShellCategory === 'all' ? REVERSE_SHELLS : REVERSE_SHELLS.filter(s => s.category === activeShellCategory);
    let currentCat = '';
    let html = '';
    shells.forEach((s, i) => {
        const realIdx = REVERSE_SHELLS.indexOf(s);
        if (activeShellCategory === 'all' && s.category !== currentCat) {
            currentCat = s.category;
            const catLabel = SHELL_CATEGORIES.find(c => c.id === currentCat)?.label || currentCat;
            html += `<div class="text-xs font-bold uppercase text-slate-500 mt-2 mb-1">${escapeHtml(catLabel)}</div>`;
        }
        const sel = realIdx === selectedShellIdx ? 'bg-violet-500/10 border-violet-500/30' : 'bg-white/[0.02] border-white/5 hover:bg-white/[0.05]';
        html += `<div class="flex items-center gap-2 px-2.5 py-1.5 rounded border cursor-pointer ${sel}" onclick="selectShell(${realIdx})">
            <span class="text-xs text-white font-medium">${escapeHtml(s.name)}</span>
            <span class="text-xs text-slate-500 truncate flex-1">${escapeHtml(s.description)}</span>
        </div>`;
    });
    document.getElementById('revshell-list').innerHTML = html;
}

function selectShell(idx) {
    selectedShellIdx = idx;
    renderShellList();
    genRevShell(idx);
}

function genRevShell(idx) {
    const shell = REVERSE_SHELLS[idx];
    if (!shell) return;
    const ip = document.getElementById('revshell-ip')?.value || '10.0.0.1';
    const port = document.getElementById('revshell-port')?.value || '4444';
    let output = shell.template.replace(/\{ip\}/g, ip).replace(/\{port\}/g, port);
    if (document.getElementById('revshell-b64wrap')?.checked && !['stabilize','listeners','web'].includes(shell.category)) {
        const b64 = btoa(output);
        output = `echo ${b64} | base64 -d | bash`;
    }
    document.getElementById('revshell-output').textContent = output;
    const listenerBtn = document.getElementById('revshell-copy-listener');
    if (listenerBtn) {
        listenerBtn.classList.toggle('hidden', ['stabilize','listeners','web'].includes(shell.category));
    }
}

function copyListenerCmd() {
    const port = document.getElementById('revshell-port')?.value || '4444';
    const shell = selectedShellIdx !== null ? REVERSE_SHELLS[selectedShellIdx] : null;
    let listener = `nc -lvnp ${port}`;
    if (shell) {
        if (shell.category === 'encrypted' && shell.name.includes('OpenSSL')) {
            listener = `openssl req -x509 -newkey rsa:4096 -keyout key.pem -out cert.pem -days 1 -nodes 2>/dev/null && openssl s_server -quiet -key key.pem -cert cert.pem -port ${port}`;
        } else if (shell.category === 'encrypted' && shell.name.includes('Ncat')) {
            listener = `ncat --ssl -lvnp ${port}`;
        } else if (shell.category === 'encrypted' && shell.name.includes('Socat')) {
            listener = 'socat file:`tty`,raw,echo=0 OPENSSL-LISTEN:' + port + ',reuseaddr,cert=cert.pem,key=key.pem,verify=0';
        } else if (shell.name.includes('Socat')) {
            listener = 'socat file:`tty`,raw,echo=0 TCP-L:' + port;
        }
    }
    navigator.clipboard.writeText(listener);
}


// === Encoder/Decoder ===
let activeEncoderCategory = 'all';

function initEncoder() {
    const filterContainer = document.getElementById('encoder-cat-filters');
    filterContainer.innerHTML = ENCODER_CATEGORIES.map(c =>
        `<button onclick="filterEncoder('${c.id}')" class="encoder-cat-btn px-2 py-1 rounded text-[11px] transition-colors ${
            c.id === 'all' ? 'bg-blue-600 text-white' : 'bg-slate-800 text-slate-300 hover:bg-blue-500/10 border border-white/5'
        }" data-cat="${c.id}">${c.label}</button>`
    ).join('');
    filterEncoder('all');
}

function filterEncoder(cat) {
    activeEncoderCategory = cat;
    document.querySelectorAll('.encoder-cat-btn').forEach(b => {
        const isActive = b.dataset.cat === cat;
        b.className = `encoder-cat-btn px-2 py-1 rounded text-[11px] transition-colors ${isActive ? 'bg-blue-600 text-white' : 'bg-slate-800 text-slate-300 hover:bg-blue-500/10 border border-white/5'}`;
    });
    renderEncoderOps();
}

function renderEncoderOps() {
    const ops = activeEncoderCategory === 'all' ? ENCODER_OPERATIONS : ENCODER_OPERATIONS.filter(o => o.category === activeEncoderCategory);
    document.getElementById('encoder-ops').innerHTML = ops.map(o =>
        `<button onclick="runEncoder('${o.fn_name}')" class="px-2.5 py-1 bg-slate-800 hover:bg-blue-500/10 border border-white/5 rounded text-[11px] text-slate-300 transition-colors" title="${escapeAttr(o.description)}">${escapeHtml(o.name)}</button>`
    ).join('');
}

async function runEncoder(fnName) {
    const input = document.getElementById('encode-input')?.value || '';
    const out = document.getElementById('encode-output');
    if (!input && !['randomPassword','timestampConvert'].includes(fnName)) { out.textContent = 'Enter text first'; return; }
    try {
        const result = await encoderFunctions[fnName](input);
        out.textContent = typeof result === 'object' ? JSON.stringify(result, null, 2) : result;
    } catch(e) { out.textContent = 'Error: ' + e.message; }
}

function copyToClipboard(elemId) {
    const text = document.getElementById(elemId)?.textContent || '';
    navigator.clipboard.writeText(text);
}

// ---- Pure JS MD5 (RFC 1321) ----
function md5(input) {
    function md5cycle(x, k) {
        let a = x[0], b = x[1], c = x[2], d = x[3];
        a = ff(a,b,c,d,k[0],7,-680876936);d=ff(d,a,b,c,k[1],12,-389564586);c=ff(c,d,a,b,k[2],17,606105819);b=ff(b,c,d,a,k[3],22,-1044525330);
        a=ff(a,b,c,d,k[4],7,-176418897);d=ff(d,a,b,c,k[5],12,1200080426);c=ff(c,d,a,b,k[6],17,-1473231341);b=ff(b,c,d,a,k[7],22,-45705983);
        a=ff(a,b,c,d,k[8],7,1770035416);d=ff(d,a,b,c,k[9],12,-1958414417);c=ff(c,d,a,b,k[10],17,-42063);b=ff(b,c,d,a,k[11],22,-1990404162);
        a=ff(a,b,c,d,k[12],7,1804603682);d=ff(d,a,b,c,k[13],12,-40341101);c=ff(c,d,a,b,k[14],17,-1502002290);b=ff(b,c,d,a,k[15],22,1236535329);
        a=gg(a,b,c,d,k[1],5,-165796510);d=gg(d,a,b,c,k[6],9,-1069501632);c=gg(c,d,a,b,k[11],14,643717713);b=gg(b,c,d,a,k[0],20,-373897302);
        a=gg(a,b,c,d,k[5],5,-701558691);d=gg(d,a,b,c,k[10],9,38016083);c=gg(c,d,a,b,k[15],14,-660478335);b=gg(b,c,d,a,k[4],20,-405537848);
        a=gg(a,b,c,d,k[9],5,568446438);d=gg(d,a,b,c,k[14],9,-1019803690);c=gg(c,d,a,b,k[3],14,-187363961);b=gg(b,c,d,a,k[8],20,1163531501);
        a=gg(a,b,c,d,k[13],5,-1444681467);d=gg(d,a,b,c,k[2],9,-51403784);c=gg(c,d,a,b,k[7],14,1735328473);b=gg(b,c,d,a,k[12],20,-1926607734);
        a=hh(a,b,c,d,k[5],4,-378558);d=hh(d,a,b,c,k[8],11,-2022574463);c=hh(c,d,a,b,k[11],16,1839030562);b=hh(b,c,d,a,k[14],23,-35309556);
        a=hh(a,b,c,d,k[1],4,-1530992060);d=hh(d,a,b,c,k[4],11,1272893353);c=hh(c,d,a,b,k[7],16,-155497632);b=hh(b,c,d,a,k[10],23,-1094730640);
        a=hh(a,b,c,d,k[13],4,681279174);d=hh(d,a,b,c,k[0],11,-358537222);c=hh(c,d,a,b,k[3],16,-722521979);b=hh(b,c,d,a,k[6],23,76029189);
        a=hh(a,b,c,d,k[9],4,-640364487);d=hh(d,a,b,c,k[12],11,-421815835);c=hh(c,d,a,b,k[15],16,530742520);b=hh(b,c,d,a,k[2],23,-995338651);
        a=ii(a,b,c,d,k[0],6,-198630844);d=ii(d,a,b,c,k[7],10,1126891415);c=ii(c,d,a,b,k[14],15,-1416354905);b=ii(b,c,d,a,k[5],21,-57434055);
        a=ii(a,b,c,d,k[12],6,1700485571);d=ii(d,a,b,c,k[3],10,-1894986606);c=ii(c,d,a,b,k[10],15,-1051523);b=ii(b,c,d,a,k[1],21,-2054922799);
        a=ii(a,b,c,d,k[8],6,1873313359);d=ii(d,a,b,c,k[15],10,-30611744);c=ii(c,d,a,b,k[6],15,-1560198380);b=ii(b,c,d,a,k[13],21,1309151649);
        a=ii(a,b,c,d,k[4],6,-145523070);d=ii(d,a,b,c,k[11],10,-1120210379);c=ii(c,d,a,b,k[2],15,718787259);b=ii(b,c,d,a,k[9],21,-343485551);
        x[0]=add32(a,x[0]);x[1]=add32(b,x[1]);x[2]=add32(c,x[2]);x[3]=add32(d,x[3]);
    }
    function cmn(q,a,b,x,s,t){a=add32(add32(a,q),add32(x,t));return add32((a<<s)|(a>>>(32-s)),b);}
    function ff(a,b,c,d,x,s,t){return cmn((b&c)|((~b)&d),a,b,x,s,t);}
    function gg(a,b,c,d,x,s,t){return cmn((b&d)|(c&(~d)),a,b,x,s,t);}
    function hh(a,b,c,d,x,s,t){return cmn(b^c^d,a,b,x,s,t);}
    function ii(a,b,c,d,x,s,t){return cmn(c^(b|(~d)),a,b,x,s,t);}
    function add32(a,b){return (a+b)&0xFFFFFFFF;}
    function md5blk(s){
        const md5blks=[];for(let i=0;i<64;i+=4)md5blks[i>>2]=s.charCodeAt(i)+(s.charCodeAt(i+1)<<8)+(s.charCodeAt(i+2)<<16)+(s.charCodeAt(i+3)<<24);
        return md5blks;
    }
    let n=input.length,state=[1732584193,-271733879,-1732584194,271733878],i;
    for(i=64;i<=n;i+=64)md5cycle(state,md5blk(input.substring(i-64,i)));
    input=input.substring(i-64);
    const tail=[0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0];
    for(i=0;i<input.length;i++)tail[i>>2]|=input.charCodeAt(i)<<((i%4)<<3);
    tail[i>>2]|=0x80<<((i%4)<<3);
    if(i>55){md5cycle(state,tail);for(i=0;i<16;i++)tail[i]=0;}
    tail[14]=n*8;
    md5cycle(state,tail);
    const hex_chr='0123456789abcdef';
    let s='';
    for(i=0;i<4;i++)for(let j=0;j<4;j++)s+=hex_chr[(state[i]>>(j*8+4))&0x0F]+hex_chr[(state[i]>>(j*8))&0x0F];
    return s;
}

// ---- Pure JS MD4 (for NTLM) ----
function md4(input) {
    function add32(a,b){return (a+b)&0xFFFFFFFF;}
    function rotl(v,s){return (v<<s)|(v>>>(32-s));}
    function f(x,y,z){return (x&y)|((~x)&z);}
    function g(x,y,z){return (x&y)|(x&z)|(y&z);}
    function h(x,y,z){return x^y^z;}
    const n = input.length;
    let words = [];
    for(let i=0;i<n;i+=4) words.push((input.charCodeAt(i)||0)+((input.charCodeAt(i+1)||0)<<8)+((input.charCodeAt(i+2)||0)<<16)+((input.charCodeAt(i+3)||0)<<24));
    const totalBits = n * 8;
    words[n>>2] |= 0x80 << ((n%4)*8);
    while(words.length % 16 !== 14) words.push(0);
    words.push(totalBits & 0xFFFFFFFF, 0);
    let a0=0x67452301,b0=0xEFCDAB89,c0=0x98BADCFE,d0=0x10325476;
    for(let i=0;i<words.length;i+=16){
        const x=words.slice(i,i+16);
        let a=a0,b=b0,c=c0,d=d0;
        const S=[3,7,11,19], O1=[0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15];
        for(let j=0;j<16;j++){a=rotl(add32(add32(a,f(b,c,d)),x[O1[j]]),S[j%4]);const t=a;a=d;d=c;c=b;b=t;}
        const S2=[3,5,9,13], O2=[0,4,8,12,1,5,9,13,2,6,10,14,3,7,11,15];
        for(let j=0;j<16;j++){a=rotl(add32(add32(add32(a,g(b,c,d)),x[O2[j]]),0x5A827999),S2[j%4]);const t=a;a=d;d=c;c=b;b=t;}
        const S3=[3,9,11,15], O3=[0,8,4,12,2,10,6,14,1,9,5,13,3,11,7,15];
        for(let j=0;j<16;j++){a=rotl(add32(add32(add32(a,h(b,c,d)),x[O3[j]]),0x6ED9EBA1),S3[j%4]);const t=a;a=d;d=c;c=b;b=t;}
        a0=add32(a0,a);b0=add32(b0,b);c0=add32(c0,c);d0=add32(d0,d);
    }
    const hex_chr='0123456789abcdef';
    let s='';
    [a0,b0,c0,d0].forEach(v=>{for(let j=0;j<4;j++)s+=hex_chr[(v>>(j*8+4))&0xF]+hex_chr[(v>>(j*8))&0xF];});
    return s;
}

// ---- Crypto.subtle hash helper ----
async function hashDigest(algo, text) {
    const buf = await crypto.subtle.digest(algo, new TextEncoder().encode(text));
    return Array.from(new Uint8Array(buf)).map(b => b.toString(16).padStart(2,'0')).join('');
}

// ---- Base32 ----
function base32Encode(input) {
    const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';
    const bytes = new TextEncoder().encode(input);
    let bits = '', result = '';
    for (const b of bytes) bits += b.toString(2).padStart(8, '0');
    while (bits.length % 5 !== 0) bits += '0';
    for (let i = 0; i < bits.length; i += 5) result += alphabet[parseInt(bits.slice(i, i+5), 2)];
    while (result.length % 8 !== 0) result += '=';
    return result;
}

function base32Decode(input) {
    const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';
    const cleaned = input.replace(/=+$/, '').toUpperCase();
    let bits = '';
    for (const c of cleaned) {
        const idx = alphabet.indexOf(c);
        if (idx === -1) throw new Error('Invalid Base32 character: ' + c);
        bits += idx.toString(2).padStart(5, '0');
    }
    const bytes = [];
    for (let i = 0; i + 8 <= bits.length; i += 8) bytes.push(parseInt(bits.slice(i, i+8), 2));
    return new TextDecoder().decode(new Uint8Array(bytes));
}

// ---- Encoder Functions Map ----
const encoderFunctions = {
    base64Encode: (input) => btoa(unescape(encodeURIComponent(input))),
    base64Decode: (input) => decodeURIComponent(escape(atob(input.trim()))),
    urlEncode: (input) => encodeURIComponent(input),
    urlDecode: (input) => decodeURIComponent(input),
    hexEncode: (input) => Array.from(new TextEncoder().encode(input)).map(b => b.toString(16).padStart(2,'0')).join(''),
    hexDecode: (input) => {
        const hex = input.replace(/\s+/g,'');
        const bytes = [];
        for(let i=0;i<hex.length;i+=2) bytes.push(parseInt(hex.substr(i,2),16));
        return new TextDecoder().decode(new Uint8Array(bytes));
    },
    htmlEncode: (input) => input.replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[c])),
    htmlDecode: (input) => { const d=document.createElement('div'); d.innerHTML=input; return d.textContent; },
    base32Encode: (input) => base32Encode(input),
    base32Decode: (input) => base32Decode(input),
    binaryEncode: (input) => Array.from(new TextEncoder().encode(input)).map(b => b.toString(2).padStart(8,'0')).join(' '),
    binaryDecode: (input) => {
        const bytes = input.trim().split(/\s+/).map(b => parseInt(b, 2));
        return new TextDecoder().decode(new Uint8Array(bytes));
    },
    decimalEncode: (input) => Array.from(new TextEncoder().encode(input)).map(b => b.toString(10)).join(' '),
    decimalDecode: (input) => {
        const bytes = input.trim().split(/\s+/).map(b => parseInt(b, 10));
        return new TextDecoder().decode(new Uint8Array(bytes));
    },
    rot13: (input) => input.replace(/[a-zA-Z]/g, c => {
        const base = c <= 'Z' ? 65 : 97;
        return String.fromCharCode(((c.charCodeAt(0) - base + 13) % 26) + base);
    }),
    rot47: (input) => input.replace(/[!-~]/g, c => String.fromCharCode(33 + ((c.charCodeAt(0) - 33 + 47) % 94))),
    unicodeEscape: (input) => Array.from(input).map(c => '\\u' + c.charCodeAt(0).toString(16).padStart(4,'0')).join(''),
    unicodeUnescape: (input) => input.replace(/\\u([0-9a-fA-F]{4})/g, (_, hex) => String.fromCharCode(parseInt(hex, 16))),
    md5Hash: (input) => md5(input),
    sha1Hash: async (input) => await hashDigest('SHA-1', input),
    sha256Hash: async (input) => await hashDigest('SHA-256', input),
    sha512Hash: async (input) => await hashDigest('SHA-512', input),
    ntlmHash: (input) => {
        // NTLM = MD4(UTF-16LE(password))
        let utf16le = '';
        for (let i = 0; i < input.length; i++) {
            const code = input.charCodeAt(i);
            utf16le += String.fromCharCode(code & 0xFF) + String.fromCharCode((code >> 8) & 0xFF);
        }
        return md4(utf16le);
    },
    jwtDecode: (input) => {
        const parts = input.trim().split('.');
        if (parts.length < 2) throw new Error('Invalid JWT: need at least header.payload');
        const b64url = s => atob(s.replace(/-/g,'+').replace(/_/g,'/').replace(/\s/g,''));
        const header = JSON.parse(b64url(parts[0]));
        const payload = JSON.parse(b64url(parts[1]));
        return { header, payload };
    },
    xorEncrypt: (input) => {
        const key = document.getElementById('encode-key')?.value || 'key';
        let result = '';
        for (let i = 0; i < input.length; i++) {
            result += (input.charCodeAt(i) ^ key.charCodeAt(i % key.length)).toString(16).padStart(2,'0');
        }
        return result;
    },
    ipConvert: (input) => {
        const trimmed = input.trim();
        let decimal;
        if (/^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$/.test(trimmed)) {
            const parts = trimmed.split('.').map(Number);
            decimal = ((parts[0] << 24) + (parts[1] << 16) + (parts[2] << 8) + parts[3]) >>> 0;
        } else if (/^0x/i.test(trimmed)) {
            decimal = parseInt(trimmed, 16) >>> 0;
        } else if (/^0/.test(trimmed) && /^[0-7.]+$/.test(trimmed)) {
            decimal = parseInt(trimmed, 8) >>> 0;
        } else {
            decimal = parseInt(trimmed, 10) >>> 0;
        }
        const d = [(decimal>>>24)&0xFF,(decimal>>>16)&0xFF,(decimal>>>8)&0xFF,decimal&0xFF];
        return `Dotted:  ${d.join('.')}\nDecimal: ${decimal}\nHex:     0x${decimal.toString(16).padStart(8,'0')}\nOctal:   0${d.map(b=>'0'+b.toString(8)).join('.')}`;
    },
    timestampConvert: (input) => {
        const trimmed = input.trim();
        if (/^\d{8,}$/.test(trimmed)) {
            const ts = parseInt(trimmed);
            const d = ts > 1e12 ? new Date(ts) : new Date(ts * 1000);
            return `UTC:   ${d.toUTCString()}\nLocal: ${d.toLocaleString()}\nISO:   ${d.toISOString()}`;
        }
        const d = new Date(trimmed || Date.now());
        if (isNaN(d.getTime())) throw new Error('Invalid date');
        return `Epoch (s):  ${Math.floor(d.getTime()/1000)}\nEpoch (ms): ${d.getTime()}\nISO:        ${d.toISOString()}\nUTC:        ${d.toUTCString()}`;
    },
    regexTest: (input) => {
        const key = document.getElementById('encode-key')?.value || '.*';
        const re = new RegExp(key, 'gm');
        const matches = [];
        let m;
        while ((m = re.exec(input)) !== null) {
            matches.push({ match: m[0], index: m.index, groups: m.slice(1) });
            if (m[0].length === 0) re.lastIndex++;
        }
        if (!matches.length) return 'No matches';
        return `${matches.length} match(es):\n` + matches.map((m, i) => `[${i}] "${m.match}" at index ${m.index}${m.groups.length ? ' groups: ' + JSON.stringify(m.groups) : ''}`).join('\n');
    },
    randomPassword: () => {
        const len = parseInt(document.getElementById('encode-input')?.value) || 16;
        const charset = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789!@#$%^&*()_+-=[]{}|;:,.<>?';
        const arr = new Uint32Array(len);
        crypto.getRandomValues(arr);
        return Array.from(arr, v => charset[v % charset.length]).join('');
    },
    reverseString: (input) => [...input].reverse().join(''),
    toUpperCase: (input) => input.toUpperCase(),
    toLowerCase: (input) => input.toLowerCase(),
    swapCase: (input) => input.replace(/[a-zA-Z]/g, c => c === c.toUpperCase() ? c.toLowerCase() : c.toUpperCase()),
    charCount: (input) => {
        const bytes = new TextEncoder().encode(input).length;
        return `Characters: ${input.length}\nBytes (UTF-8): ${bytes}\nWords: ${input.trim().split(/\s+/).filter(Boolean).length}\nLines: ${input.split('\n').length}`;
    },
    urlParse: (input) => {
        try {
            const u = new URL(input);
            return `Protocol: ${u.protocol}\nHost:     ${u.host}\nHostname: ${u.hostname}\nPort:     ${u.port || '(default)'}\nPathname: ${u.pathname}\nSearch:   ${u.search}\nHash:     ${u.hash}\nOrigin:   ${u.origin}`;
        } catch { return 'Invalid URL'; }
    },
};


// === Port Reference ===
let activePortCategory = 'all';

function initPorts() {
    const filterContainer = document.getElementById('port-cat-filters');
    filterContainer.innerHTML = PORT_CATEGORIES.map(c =>
        `<button onclick="filterPortCat('${c.id}')" class="port-cat-btn px-2 py-1 rounded text-[11px] transition-colors ${
            c.id === 'all' ? 'bg-emerald-600 text-white' : 'bg-slate-800 text-slate-300 hover:bg-emerald-500/10 border border-white/5'
        }" data-cat="${c.id}">${c.label}</button>`
    ).join('');
    renderPorts(PORT_REFERENCE);
}

function filterPortCat(cat) {
    activePortCategory = cat;
    document.querySelectorAll('.port-cat-btn').forEach(b => {
        const isActive = b.dataset.cat === cat;
        b.className = `port-cat-btn px-2 py-1 rounded text-[11px] transition-colors ${isActive ? 'bg-emerald-600 text-white' : 'bg-slate-800 text-slate-300 hover:bg-emerald-500/10 border border-white/5'}`;
    });
    filterPorts();
}

function renderPorts(ports) {
    document.getElementById('port-count').textContent = ports.length + ' ports';
    document.getElementById('port-list').innerHTML = ports.map(p => {
        const vulnClass = p.common_vulns.includes('RCE') || p.common_vulns.includes('CVE') ? 'text-rose-400' : 'text-amber-400/80';
        const toolLinks = p.tools.split(', ').map(t => `<span class="text-violet-400 hover:text-violet-300 cursor-pointer" onclick="jumpToTool('${escapeAttr(t.trim())}')">${escapeHtml(t.trim())}</span>`).join(', ');
        return `<tr class="border-b border-white/[0.03] hover:bg-white/[0.03]">
            <td class="px-2 py-1.5 text-violet-400 font-bold">${p.port}</td>
            <td class="px-2 py-1.5 text-emerald-400">${escapeHtml(p.service)}</td>
            <td class="px-2 py-1.5 text-slate-500">${p.protocol}</td>
            <td class="px-2 py-1.5 text-slate-400">${escapeHtml(p.default_creds)}</td>
            <td class="px-2 py-1.5 ${vulnClass}">${escapeHtml(p.common_vulns)}</td>
            <td class="px-2 py-1.5">${toolLinks}</td>
        </tr>`;
    }).join('');
}

function filterPorts() {
    const q = document.getElementById('port-search')?.value?.toLowerCase() || '';
    let ports = PORT_REFERENCE;
    if (activePortCategory !== 'all') ports = ports.filter(p => p.category === activePortCategory);
    if (q) {
        ports = ports.filter(p =>
            p.port.toString().includes(q) || p.service.toLowerCase().includes(q) ||
            p.common_vulns.toLowerCase().includes(q) || p.tools.toLowerCase().includes(q) ||
            p.default_creds.toLowerCase().includes(q) || p.protocol.toLowerCase().includes(q)
        );
    }
    renderPorts(ports);
}

function jumpToTool(toolName) {
    switchManualTab('execute');
    const searchInput = document.getElementById('tool-search');
    if (searchInput) { searchInput.value = toolName; filterTools(); }
    const match = allTools.find(t => t.name.toLowerCase() === toolName.toLowerCase() || t.id.toLowerCase() === toolName.toLowerCase());
    if (match) setTimeout(() => selectManualTool(match.id), 200);
}


// === Wordlist Management ===
async function loadWordlists() {
    try {
        const { data, error } = await spectraApi.get('/api/v1/wordlists');
        const wordlists = data?.wordlists || data?.local || [];
        const presets = data?.presets || [];

        let html = '';
        if (wordlists.length) {
            html += wordlists.map(w => `
                <div class="flex items-center gap-2 text-xs px-2 py-1.5 rounded bg-white/[0.02] hover:bg-white/[0.05] group">
                    <i data-lucide="file-text" class="w-4 h-4 inline-block text-amber-400/60 shrink-0"></i>
                    <span class="text-white truncate flex-1 font-mono">${escapeHtml(w.name || w)}</span>
                    ${w.size ? `<span class="text-slate-500 text-xs shrink-0">${w.size}</span>` : ''}
                    <button onclick="navigator.clipboard.writeText('${escapeAttr(w.path || w.name || w)}')" class="opacity-0 group-hover:opacity-100 text-slate-400 hover:text-white transition-all" title="Copy path"><i data-lucide="copy" class="w-3.5 h-3.5 inline-block"></i></button>
                </div>
            `).join('');
        }

        if (presets.length) {
            html += '<div class="text-xs text-slate-500 uppercase font-bold mt-3 mb-1">Available for Download</div>';
            html += presets.map(p => `
                <div class="flex items-center gap-2 text-xs px-2 py-1.5 rounded bg-white/[0.02] ${p.downloaded ? 'opacity-50' : 'hover:bg-white/[0.05]'}">
                    <i data-lucide="download" class="w-4 h-4 inline-block text-blue-400/60 shrink-0"></i>
                    <span class="text-slate-300 truncate flex-1">${escapeHtml(p.name)} <span class="text-slate-500">(${p.entries} entries)</span></span>
                    ${!p.downloaded ? `<button onclick="downloadPreset('${escapeAttr(p.id)}')" class="px-1.5 py-0.5 bg-blue-600/80 hover:bg-blue-500 text-white rounded text-xs transition-colors">Get</button>` : '<span class="text-emerald-400 text-xs">\u2713</span>'}
                </div>
            `).join('');
        }

        document.getElementById('wordlist-list').innerHTML = html || '<div class="text-slate-500 text-xs">No wordlists found</div>';
        if (typeof lucide !== 'undefined') lucide.createIcons();
    } catch(e) {
        document.getElementById('wordlist-list').innerHTML = '<div class="text-rose-400 text-xs">Failed to load</div>';
    }
}

async function downloadPreset(presetId) {
    try {
        await spectraApi.post(`/api/v1/wordlists/download-preset/${encodeURIComponent(presetId)}`);
        loadWordlists();
    } catch(e) { console.error(e); }
}

async function uploadWordlist(input) {
    const file = input.files?.[0];
    if (!file) return;
    const form = new FormData();
    form.append('file', file);
    try {
        await spectraApi.post('/api/v1/wordlists/upload', form);
        loadWordlists();
    } catch(e) { console.error(e); }
    input.value = '';
}

async function refreshWordlistOptions() {
    try {
        const { data } = await spectraApi.get('/api/v1/wordlists');
        const wordlists = data?.wordlists || data?.local || [];
        const dl = document.getElementById('wordlist-options');
        if (dl) {
            dl.innerHTML = wordlists.map(w => `<option value="${escapeAttr(w.path || w.name || w)}">`).join('');
        }
    } catch(e) { /* ignore */ }
}


// Init
document.addEventListener('DOMContentLoaded', async () => {
    // Activate the initial tab via tabs.js so ARIA state is correct from the start
    if (window.activateTab) window.activateTab('manual-tabs', 'execute');
    loadTools();
    showTip();
    initRevShells();
    initEncoder();
    initPorts();
    loadWordlists();

    // Try loading manual state from server before falling back to localStorage
    const serverLoaded = await loadManualStateFromServer();
    if (serverLoaded) {
        console.debug('Manual mode state loaded from server');
    }

    loadChecklist();
    loadNotes();
    loadEvidence();
    initLFI();
    initSQLi();
    initPrivEsc();
    renderADCommands();
    initEvidenceDragDrop();
    initClipboardPaste();
});


const debouncedFilterTools = debounce(filterTools);
const debouncedFilterHistory = debounce(filterHistory);
const debouncedFilterPorts = debounce(filterPorts);
const debouncedFilterLFI = debounce(filterLFI);
const debouncedFilterSQLi = debounce(filterSQLi);
const debouncedFilterPrivEsc = debounce(filterPrivEsc);

// Expose functions to global scope for HTML event handlers
window.switchManualTab = switchManualTab;
window.nextTip = nextTip;
window.startSession = startSession;
window.exportSession = exportSession;
window.toggleScopePanel = toggleScopePanel;
window.addScopeTarget = addScopeTarget;
window.addScopeExclusion = addScopeExclusion;
window.saveScope = saveScope;
window.quickRun = quickRun;
window.debouncedFilterTools = debouncedFilterTools;
window.executeManualTool = executeManualTool;
window.clearOutput = clearOutput;
window.openDiffModal = openDiffModal;
window.toggleHistoryPanel = toggleHistoryPanel;
window.debouncedFilterHistory = debouncedFilterHistory;
window.filterHistory = filterHistory;
window.sortHistory = sortHistory;
window.addPipelineStep = addPipelineStep;
window.runPipeline = runPipeline;
window.loadPipelineTemplate = loadPipelineTemplate;
window.searchCVEs = searchCVEs;
window.loadChecklist = loadChecklist;
window.resetChecklist = resetChecklist;
window.filterNotes = filterNotes;
window.createNote = createNote;
window.wrapNoteText = wrapNoteText;
window.toggleNotePreview = toggleNotePreview;
window.onNoteEdit = onNoteEdit;
window.deleteNote = deleteNote;
window.saveCurrentNote = saveCurrentNote;
window.uploadEvidence = uploadEvidence;
window.pasteEvidence = pasteEvidence;
window.filterEvidence = filterEvidence;
window.switchHelperTab = switchHelperTab;
window.copyToClipboard = copyToClipboard;
window.copyListenerCmd = copyListenerCmd;
window.debouncedFilterPorts = debouncedFilterPorts;
window.loadWordlists = loadWordlists;
window.uploadWordlist = uploadWordlist;
window.setCVSS = setCVSS;
window.parseCVSSVector = parseCVSSVector;
window.copyCVSSVector = copyCVSSVector;
window.debouncedFilterLFI = debouncedFilterLFI;
window.filterLFIOS = filterLFIOS;
window.debouncedFilterSQLi = debouncedFilterSQLi;
window.debouncedFilterPrivEsc = debouncedFilterPrivEsc;
window.renderADCommands = renderADCommands;
window.selectManualTool = selectManualTool;
window.lookupCVEsFor = lookupCVEsFor;
window.runToolOn = runToolOn;
window.chainToTool = chainToTool;
window.removePipelineStep = removePipelineStep;
window.updatePipelineStep = updatePipelineStep;
window.viewHistoryOutput = viewHistoryOutput;
window.rerunFromHistory = rerunFromHistory;
window.runDiff = runDiff;
window.launchMetasploit = launchMetasploit;
window.filterShells = filterShells;
window.selectShell = selectShell;
window.filterEncoder = filterEncoder;
window.runEncoder = runEncoder;
window.filterPortCat = filterPortCat;
window.jumpToTool = jumpToTool;
window.downloadPreset = downloadPreset;
window.removeScopeTarget = removeScopeTarget;
window.removeScopeExclusion = removeScopeExclusion;
window.toggleAccordion = toggleAccordion;
window.toggleChecklistItem = toggleChecklistItem;
window.toggleChecklistNotes = toggleChecklistNotes;
window.saveChecklistNote = saveChecklistNote;
window.openNote = openNote;
window.previewEvidence = previewEvidence;
window.removeEvidence = removeEvidence;
window.filterSQLiCat = filterSQLiCat;
window.filterPrivEscFn = filterPrivEscFn;
window.refreshWordlistOptions = refreshWordlistOptions;
window.showModal = showModal;
