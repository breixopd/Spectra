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
