/**
 * 3D Attack Graph Visualization using Three.js
 * 
 * Renders the attack path as a 3D force-directed graph:
 * - Nodes: hosts, services, vulnerabilities, exploits
 * - Edges: attack flow with success/fail coloring
 * - Interactive: rotate, zoom, click nodes for details
 */

let scene, camera, renderer, controls;
let nodes = [], edges = [], nodeObjects = [], edgeObjects = [];
let graphData = { nodes: [], edges: [] };

const NODE_COLORS = {
    target: 0x8b5cf6,     // violet
    service: 0x10b981,    // emerald
    vulnerability: 0xf59e0b, // amber
    exploit: 0xf43f5e,    // rose
    success: 0x34d399,    // green
    shell: 0x06b6d4,      // cyan
};

function initAttackGraph(containerId) {
    const container = document.getElementById(containerId);
    if (!container) return;

    // Scene
    scene = new THREE.Scene();
    scene.background = new THREE.Color(0x0a0e1a);
    scene.fog = new THREE.FogExp2(0x0a0e1a, 0.008);

    // Camera
    camera = new THREE.PerspectiveCamera(60, container.clientWidth / container.clientHeight, 0.1, 1000);
    camera.position.set(0, 30, 50);

    // Renderer
    renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setSize(container.clientWidth, container.clientHeight);
    renderer.setPixelRatio(window.devicePixelRatio);
    container.appendChild(renderer.domElement);

    // OrbitControls
    if (typeof THREE.OrbitControls !== 'undefined') {
        controls = new THREE.OrbitControls(camera, renderer.domElement);
        controls.enableDamping = true;
        controls.dampingFactor = 0.05;
        controls.maxDistance = 200;
        controls.minDistance = 10;
    }

    // Ambient light
    scene.add(new THREE.AmbientLight(0x404060, 0.5));

    // Point light
    const light = new THREE.PointLight(0x8b5cf6, 1, 200);
    light.position.set(0, 50, 0);
    scene.add(light);

    // Grid helper
    const grid = new THREE.GridHelper(100, 20, 0x1e293b, 0x0f172a);
    grid.position.y = -10;
    scene.add(grid);

    // Resize handler
    window.addEventListener('resize', () => {
        camera.aspect = container.clientWidth / container.clientHeight;
        camera.updateProjectionMatrix();
        renderer.setSize(container.clientWidth, container.clientHeight);
    });

    animate();
}

function animate() {
    requestAnimationFrame(animate);

    // Gentle rotation of nodes
    nodeObjects.forEach((obj, i) => {
        obj.rotation.y += 0.005;
        // Floating effect
        obj.position.y += Math.sin(Date.now() * 0.001 + i) * 0.005;
    });

    if (controls) controls.update();
    renderer.render(scene, camera);
}

function addNode(id, type, label, x, y, z) {
    const color = NODE_COLORS[type] || 0x64748b;
    const size = type === 'target' ? 2 : type === 'success' ? 1.8 : 1.2;

    // Create node geometry
    const geometry = type === 'target'
        ? new THREE.OctahedronGeometry(size)
        : type === 'success'
            ? new THREE.IcosahedronGeometry(size)
            : new THREE.SphereGeometry(size, 16, 16);

    const material = new THREE.MeshPhongMaterial({
        color: color,
        emissive: color,
        emissiveIntensity: 0.3,
        transparent: true,
        opacity: 0.85,
    });

    const mesh = new THREE.Mesh(geometry, material);
    mesh.position.set(x || 0, y || 0, z || 0);
    mesh.userData = { id, type, label };

    scene.add(mesh);
    nodeObjects.push(mesh);

    // Add glow effect for important nodes
    if (type === 'target' || type === 'success') {
        const glowGeom = new THREE.SphereGeometry(size * 1.5, 16, 16);
        const glowMat = new THREE.MeshBasicMaterial({
            color: color,
            transparent: true,
            opacity: 0.1,
        });
        const glow = new THREE.Mesh(glowGeom, glowMat);
        mesh.add(glow);
    }

    return mesh;
}

function addEdge(fromNode, toNode, success) {
    const from = fromNode.position;
    const to = toNode.position;

    const points = [from, to];
    const geometry = new THREE.BufferGeometry().setFromPoints(points);
    const material = new THREE.LineBasicMaterial({
        color: success ? 0x34d399 : 0x475569,
        transparent: true,
        opacity: success ? 0.8 : 0.3,
    });

    const line = new THREE.Line(geometry, material);
    scene.add(line);
    edgeObjects.push(line);
    return line;
}

function loadAttackGraph(data) {
    // Clear existing
    nodeObjects.forEach(obj => scene.remove(obj));
    edgeObjects.forEach(obj => scene.remove(obj));
    nodeObjects = [];
    edgeObjects = [];

    if (!data || !data.nodes || data.nodes.length === 0) return;

    // Position nodes in a spiral layout
    const nodeMap = {};
    data.nodes.forEach((node, i) => {
        const angle = (i / data.nodes.length) * Math.PI * 4;
        const radius = 10 + i * 2;
        const x = Math.cos(angle) * radius;
        const z = Math.sin(angle) * radius;
        const y = (node.type === 'target' ? 5 : 0) + Math.random() * 3;

        const mesh = addNode(node.id, node.type, node.label, x, y, z);
        nodeMap[node.id] = mesh;
    });

    // Add edges
    if (data.edges) {
        data.edges.forEach(edge => {
            const from = nodeMap[edge.from];
            const to = nodeMap[edge.to];
            if (from && to) {
                addEdge(from, to, edge.success);
            }
        });
    }

    // Center camera on graph
    camera.lookAt(0, 0, 0);
}

// Build attack graph from mission findings
function buildGraphFromMission(findings, services, target) {
    const data = { nodes: [], edges: [] };

    // Target node
    data.nodes.push({ id: 'target', type: 'target', label: target });

    // Service nodes
    const serviceIds = {};
    (services || []).forEach((svc, i) => {
        const id = `svc-${svc.port}`;
        serviceIds[svc.port] = id;
        data.nodes.push({ id, type: 'service', label: `${svc.service || 'unknown'}:${svc.port}` });
        data.edges.push({ from: 'target', to: id, success: true });
    });

    // Finding/vulnerability nodes
    (findings || []).forEach((f, i) => {
        const severity = (f.severity || 'info').toLowerCase();
        const type = severity === 'critical' ? 'exploit' : severity === 'high' ? 'vulnerability' : 'vulnerability';
        const id = `finding-${i}`;
        const label = f.name || f.title || f['template-id'] || `Finding ${i + 1}`;

        data.nodes.push({ id, type, label: label.substring(0, 30) });

        // Connect to service if port matches
        const port = f.port || f.portid;
        if (port && serviceIds[port]) {
            data.edges.push({ from: serviceIds[port], to: id, success: true });
        } else {
            data.edges.push({ from: 'target', to: id, success: true });
        }

        // If it's a confirmed exploit, add success node
        if (f.confirmed || f.source === 'exploitation') {
            const successId = `success-${i}`;
            data.nodes.push({ id: successId, type: 'success', label: 'Access Gained' });
            data.edges.push({ from: id, to: successId, success: true });
        }
    });

    return data;
}
