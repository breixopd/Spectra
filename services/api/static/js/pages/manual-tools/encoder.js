// === Encoder/Decoder ===
let activeEncoderCategory = 'all';

function initEncoder() {
    const filterContainer = document.getElementById('encoder-cat-filters');
    filterContainer.innerHTML = ENCODER_CATEGORIES.map(c =>
        `<button data-action="filterEncoder" data-value="${c.id}" class="encoder-cat-btn px-2 py-1 rounded text-[11px] transition-colors ${
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
        `<button data-action="runEncoder" data-value="${o.fn_name}" class="px-2.5 py-1 bg-slate-800 hover:bg-blue-500/10 border border-white/5 rounded text-[11px] text-slate-300 transition-colors" title="${escapeAttr(o.description)}">${escapeHtml(o.name)}</button>`
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
            return `UTC:   ${d.toUTCString()}\nLocal: ${d.toLocaleString('en-US')}\nISO:   ${d.toISOString()}`;
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
