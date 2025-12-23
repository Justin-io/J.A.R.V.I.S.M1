const socket = io();

// --- CONFIGURATION ---
const UPDATE_INTERVAL_MS = 1000;

// --- DOM ELEMENTS ---
const statusIndicator = document.getElementById('connection-status');
const aiStatusText = document.getElementById('ai-status');
const terminalContent = document.getElementById('terminal-content');
const timeDisplay = document.getElementById('time-display');

// Server Bars
const server1Bar = document.getElementById('server-1-bar');
const server1Val = document.getElementById('server-1-val'); // Main Frame (CPU)
const server2Bar = document.getElementById('server-2-bar');
const server2Val = document.getElementById('server-2-val'); // Data Core (RAM)
const server3Bar = document.getElementById('server-3-bar');
const server3Val = document.getElementById('server-3-val'); // Storage (Disk)

const sysTemp = document.getElementById('sys-temp');
const sysPower = document.getElementById('sys-power');
const memVal = document.getElementById('mem-val');

// --- UTILITIES ---
function updateTime() {
    const now = new Date();
    if (timeDisplay) {
        timeDisplay.innerText = now.toLocaleTimeString('en-US', { hour12: false });
    }
}
setInterval(updateTime, 1000);
updateTime();

// Helper to add logs
function addLog(text, type = 'system') {
    if (!terminalContent) return;

    // Check if duplicate to avoid spam
    if (terminalContent.lastChild && terminalContent.lastChild.textContent.includes(text)) {
        return;
    }

    const entry = document.createElement('div');
    entry.className = 'text-cyan-300 opacity-80 hover:opacity-100 transition-opacity duration-200 border-l-2 border-transparent hover:border-cyan-500 pl-1 mb-1 font-mono text-xs';

    let prefix = ">>";
    let colorClass = "text-cyan-600";

    if (type === 'user') {
        prefix = "[USER]";
        colorClass = "text-yellow-500";
        entry.className = entry.className.replace('text-cyan-300', 'text-yellow-300');
    } else if (type === 'status') {
        prefix = "[SYS]";
        colorClass = "text-red-500";
    }

    const time = new Date().toLocaleTimeString('en-US', { hour12: false });
    entry.innerHTML = `<span class="text-[10px] ${colorClass} mr-2 font-bold">${prefix} [${time}]</span> <span>${text}</span>`;

    terminalContent.appendChild(entry);

    // Prune logs if too many
    if (terminalContent.children.length > 50) {
        terminalContent.removeChild(terminalContent.firstChild);
    }

    terminalContent.scrollTop = terminalContent.scrollHeight;
}

// --- THREE.JS NEURAL VISUALIZATION ---
(function initThreeJS() {
    const container = document.getElementById('canvas-container');
    if (!container) return;

    const scene = new THREE.Scene();
    // Subtler fog for deep space feel
    scene.fog = new THREE.FogExp2(0x020408, 0.003);

    const camera = new THREE.PerspectiveCamera(75, 1, 0.1, 1000);
    camera.position.z = 20;

    const renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true });
    renderer.setSize(800, 800);
    renderer.setPixelRatio(window.devicePixelRatio);

    // Clear existing children if any
    while (container.firstChild) {
        container.removeChild(container.firstChild);
    }
    container.appendChild(renderer.domElement);

    // Grouping
    const brainGroup = new THREE.Group();
    scene.add(brainGroup);

    // 1. INNER CORE (Dense Wireframe Sphere)
    const coreGeo = new THREE.IcosahedronGeometry(4, 2);
    const coreMat = new THREE.MeshBasicMaterial({
        color: 0x00f3ff,
        wireframe: true,
        transparent: true,
        opacity: 0.15
    });
    const coreMesh = new THREE.Mesh(coreGeo, coreMat);
    brainGroup.add(coreMesh);

    // 2. NEURAL CLOUD (Nodes & Lines)
    const particleCount = 400;
    const cloudRadius = 9;
    const particlesData = [];
    let particlePositions = new Float32Array(particleCount * 3);

    const pMaterial = new THREE.PointsMaterial({
        color: 0x00f3ff,
        size: 0.15,
        blending: THREE.AdditiveBlending,
        transparent: true,
        opacity: 0.8
    });

    for (let i = 0; i < particleCount; i++) {
        const r = cloudRadius + (Math.random() - 0.5) * 4;
        const theta = Math.random() * Math.PI * 2;
        const phi = Math.acos((Math.random() * 2) - 1);

        const x = r * Math.sin(phi) * Math.cos(theta);
        const y = r * Math.sin(phi) * Math.sin(theta);
        const z = r * Math.cos(phi);

        particlePositions[i * 3] = x;
        particlePositions[i * 3 + 1] = y;
        particlePositions[i * 3 + 2] = z;

        particlesData.push({
            velocity: new THREE.Vector3(
                (-1 + Math.random() * 2) * 0.02,
                (-1 + Math.random() * 2) * 0.02,
                (-1 + Math.random() * 2) * 0.02
            ),
            originalPos: new THREE.Vector3(x, y, z)
        });
    }

    const particlesGeo = new THREE.BufferGeometry();
    particlesGeo.setAttribute('position', new THREE.BufferAttribute(particlePositions, 3));
    const particleSystem = new THREE.Points(particlesGeo, pMaterial);
    brainGroup.add(particleSystem);

    // Lines setup
    const linesGeo = new THREE.BufferGeometry();
    const linePositions = new Float32Array(particleCount * particleCount * 3);
    const lineColors = new Float32Array(particleCount * particleCount * 3);

    linesGeo.setAttribute('position', new THREE.BufferAttribute(linePositions, 3));
    linesGeo.setAttribute('color', new THREE.BufferAttribute(lineColors, 3));

    const lMaterial = new THREE.LineBasicMaterial({
        vertexColors: true,
        blending: THREE.AdditiveBlending,
        transparent: true,
        opacity: 0.2
    });

    const linesMesh = new THREE.LineSegments(linesGeo, lMaterial);
    brainGroup.add(linesMesh);

    // 3. ORBITAL RINGS
    const ringGroup = new THREE.Group();
    brainGroup.add(ringGroup);

    function createOrbitalRing(radius, count, speedX, speedY) {
        const ringGeo = new THREE.BufferGeometry();
        const ringPos = new Float32Array(count * 3);
        for (let i = 0; i < count; i++) {
            const theta = (i / count) * Math.PI * 2;
            ringPos[i * 3] = Math.cos(theta) * radius;
            ringPos[i * 3 + 1] = Math.sin(theta) * radius;
            ringPos[i * 3 + 2] = (Math.random() - 0.5) * 0.5;
        }
        ringGeo.setAttribute('position', new THREE.BufferAttribute(ringPos, 3));
        const ringMat = new THREE.PointsMaterial({ color: 0x00f3ff, size: 0.1, transparent: true, opacity: 0.6 });
        const ring = new THREE.Points(ringGeo, ringMat);
        ring.userData = { speedX, speedY };
        return ring;
    }

    const ring1 = createOrbitalRing(11, 100, 0.005, 0.01);
    const ring2 = createOrbitalRing(13, 80, -0.01, 0.002);
    ringGroup.add(ring1);
    ringGroup.add(ring2);

    // Animation Loop
    function animate() {
        requestAnimationFrame(animate);

        brainGroup.rotation.y += 0.002;
        coreMesh.rotation.x -= 0.005;
        coreMesh.rotation.z += 0.002;

        let vertexpos = 0;
        let colorpos = 0;
        let numConnected = 0;

        for (let i = 0; i < particleCount; i++) {
            const p = particlesData[i];
            particlePositions[i * 3] += p.velocity.x;
            particlePositions[i * 3 + 1] += p.velocity.y;
            particlePositions[i * 3 + 2] += p.velocity.z;

            // Bounce back
            if (Math.abs(particlePositions[i * 3] - p.originalPos.x) > 1) p.velocity.x = -p.velocity.x;
            if (Math.abs(particlePositions[i * 3 + 1] - p.originalPos.y) > 1) p.velocity.y = -p.velocity.y;
            if (Math.abs(particlePositions[i * 3 + 2] - p.originalPos.z) > 1) p.velocity.z = -p.velocity.z;
        }
        particlesGeo.attributes.position.needsUpdate = true;

        // Dynamic Lines (Optimized)
        const connectionDist = 2.5;
        // Only check a subset per frame or just accept the O(N^2) for N=400 on modern PC
        // For N=400, N^2=160,000 checks. Doable in JS. Maybe limit connections to first 1000 to save buffers?
        // We'll stick to full check but strict distance to keep line count low

        let lineIdx = 0;
        for (let i = 0; i < particleCount; i++) {
            for (let j = i + 1; j < particleCount; j++) {
                const dx = particlePositions[i * 3] - particlePositions[j * 3];
                const dy = particlePositions[i * 3 + 1] - particlePositions[j * 3 + 1];
                const dz = particlePositions[i * 3 + 2] - particlePositions[j * 3 + 2];
                const distSq = dx * dx + dy * dy + dz * dz;

                if (distSq < connectionDist * connectionDist) {
                    const alpha = 1.0 - Math.sqrt(distSq) / connectionDist;

                    linePositions[lineIdx++] = particlePositions[i * 3];
                    linePositions[lineIdx++] = particlePositions[i * 3 + 1];
                    linePositions[lineIdx++] = particlePositions[i * 3 + 2];

                    linePositions[lineIdx++] = particlePositions[j * 3];
                    linePositions[lineIdx++] = particlePositions[j * 3 + 1];
                    linePositions[lineIdx++] = particlePositions[j * 3 + 2];

                    lineColors[colorpos++] = 0; lineColors[colorpos++] = alpha; lineColors[colorpos++] = 1;
                    lineColors[colorpos++] = 0; lineColors[colorpos++] = alpha; lineColors[colorpos++] = 1;

                    numConnected++;
                }
            }
        }

        linesMesh.geometry.setDrawRange(0, numConnected * 2);
        linesMesh.geometry.attributes.position.needsUpdate = true;
        linesMesh.geometry.attributes.color.needsUpdate = true;

        ring1.rotation.x += ring1.userData.speedX;
        ring1.rotation.y += ring1.userData.speedY;
        ring2.rotation.x += ring2.userData.speedX;
        ring2.rotation.y += ring2.userData.speedY;

        renderer.render(scene, camera);
    }
    animate();
})();

// --- SOCKET EVENTS ---
socket.on('connect', () => {
    statusIndicator.textContent = "CONNECTED";
    statusIndicator.className = "font-bold status-pulse bg-cyan-900/40 px-3 py-1 rounded-sm border border-cyan-500/30 text-cyan-300";
    addLog("Secure uplink established with Neural Core.", 'status');
    aiStatusText.innerHTML = "NEURAL ENGINE: <span class='text-cyan-300 drop-shadow-[0_0_10px_rgba(0,243,255,0.8)]'>ONLINE</span>";
});

socket.on('disconnect', () => {
    statusIndicator.textContent = "DISCONNECTED";
    statusIndicator.className = "font-bold bg-red-900/40 px-3 py-1 rounded-sm border border-red-500/30 text-red-500";
    addLog("SIGNAL LOST. Attempting reconnect...", 'status');
});

socket.on('status_update', (data) => {
    const status = data.status; // 'listening', 'processing', 'speaking', 'idle'
    const reactor = document.querySelector('canvas'); // Target the 3D canvas for effects if possible, or just the container

    if (status === 'listening') {
        aiStatusText.innerHTML = "STATUS: <span class='text-yellow-400 animate-pulse'>LISTENING</span>";
        // Visual cue
        if (reactor) reactor.style.filter = "brightness(1.5) drop-shadow(0 0 10px yellow)";
    } else if (status === 'processing') {
        aiStatusText.innerHTML = "STATUS: <span class='text-purple-400 animate-pulse'>PROCESSING</span>";
        if (reactor) reactor.style.filter = "brightness(1.5) drop-shadow(0 0 10px purple)";
    } else if (status === 'speaking') {
        aiStatusText.innerHTML = "STATUS: <span class='text-cyan-400 animate-pulse'>SPEAKING</span>";
        if (reactor) reactor.style.filter = "brightness(1.2) drop-shadow(0 0 15px cyan)";
    } else {
        aiStatusText.innerHTML = "NEURAL ENGINE: <span class='text-cyan-300'>ONLINE</span>";
        if (reactor) reactor.style.filter = "none";
    }
});

socket.on('new_log', (data) => {
    addLog(data.message, data.type || 'system');
});

socket.on('system_stats', (stats) => {
    // 1. CPU (Main Frame)
    if (stats.cpu !== undefined) {
        if (server1Bar) {
            server1Bar.style.width = `${stats.cpu}%`;
            // Color change based on load
            if (stats.cpu > 90) server1Bar.className = "sys-bar bg-red-500 h-full shadow-[0_0_8px_#f00]";
            else server1Bar.className = "sys-bar bg-cyan-400 h-full shadow-[0_0_8px_#00f3ff]";
        }
        if (server1Val) server1Val.innerText = stats.cpu + "%";
    }

    // 2. Memory (Data Core)
    if (stats.memory !== undefined) {
        if (server2Bar) server2Bar.style.width = `${stats.memory}%`;
        if (server2Val) server2Val.innerText = stats.memory + "%";
        if (memVal) memVal.innerText = `MEM:${stats.memory}%`;
    }

    // 3. Disk (Storage)
    if (stats.disk !== undefined) {
        if (server3Bar) server3Bar.style.width = `${stats.disk}%`;
    }

    // 4. Power / Battery
    if (stats.battery !== undefined) {
        const charging = stats.plugged ? "⚡" : "";
        if (sysPower) sysPower.innerText = `${stats.battery}%${charging}`;

        // Use Server 3 text for battery info if disk is redundant, or just keep as is.
        // Let's hide specific battery in server 3 and keep it in the specific box.
    }

    // 5. Temp
    if (stats.temp !== undefined) {
        if (sysTemp) sysTemp.innerText = Math.round(stats.temp) + "°C";
    }

    // 6. PID
    if (stats.pid !== undefined) {
        const pidEl = document.getElementById('pid-val');
        if (pidEl) pidEl.innerText = `PID:${stats.pid}`;
    }

    // Update Network Graph (Fake it based on CPU activity for liveness)
    updateNetworkGraph(stats.cpu);
});

// Mock network graph activity driven by CPU
function updateNetworkGraph(cpuLoad) {
    const bars = document.querySelectorAll('#network-graph .sys-bar');
    bars.forEach(bar => {
        // Base random + cpu influence
        const h = Math.random() * 30 + (cpuLoad ? cpuLoad * 0.5 : 10);
        bar.style.height = Math.min(100, h) + '%';
    });
}

