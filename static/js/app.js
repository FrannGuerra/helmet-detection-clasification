const socket = io();

let alertCount        = 0;
let currentTimeFilter = '5min';
let currentMode       = null;
let selectedCameraId  = null;
let camerasData       = [];
let activeCameras     = [];    // Cámaras del modo actual
let hlsPlayers        = {};
let leafletMap        = null;
let heatLayer         = null;
let cameraMarkers     = {};
let perCameraMetrics  = {};

// Milestone 2 State Variables (F16-F27)
let isAudioUnlocked   = false;
let audioContext      = null;
let alertSoundMuted   = (localStorage.getItem('alertSoundMuted') === 'true') || (localStorage.getItem('helmet_alert_muted') === 'true');
let activeTab         = 'monitoring'; // 'monitoring' | 'dashboard'
let chartHourly       = null;
let chartCamera       = null;

// Timers de auto-refresh (para poder limpiarlos)
let metricsInterval = null;
let heatmapInterval = null;


// INIT
// Al cargar la página: obtener la lista completa de cámaras y mostrar el selector.

fetch('/api/cameras')
    .then(r => r.json())
    .then(cameras => {
        camerasData = cameras;
        // Mostrar selector de modo (ya está visible por defecto en el HTML)
    })
    .catch(err => console.error('[Init]', err));

// Inicializar estado del toggle de audio
document.addEventListener('DOMContentLoaded', () => {
    updateAudioToggleUI();
});
if (document.readyState !== 'loading') {
    updateAudioToggleUI();
}

// Desbloquear audio en el primer clic del usuario (autoplay policy)
document.addEventListener('click', unlockAudioContext, { once: true });


// SELECTOR DE MODO

async function startMode() {
    unlockAudioContext();
    showLoadingOverlay('Iniciando procesamiento...');

    try {
        const res = await fetch('/api/start', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({})
        });

        const data = await res.json();

        if (!res.ok || data.error) {
            hideLoadingOverlay();
            alert(data.error || `Error del servidor (HTTP ${res.status})`);
            return;
        }

        currentMode = 'live';
        activeCameras = data.cameras || [];

        // Actualizar UI
        document.getElementById('camera-count').textContent = `${activeCameras.length} cámaras`;
        document.getElementById('cameras-title').textContent = 'Cámaras en vivo';

        // Badge de estado
        const badge     = document.getElementById('live-badge');
        const badgeText = document.getElementById('live-badge-text');
        badge.className = 'flex items-center space-x-2 bg-green-500/20 px-3 py-1.5 rounded-lg border border-green-500/30';
        badge.querySelector('.w-2').className = 'w-2 h-2 bg-green-500 rounded-full animate-pulse';
        badgeText.className = 'text-xs font-medium text-green-400';
        badgeText.textContent = 'En vivo';

        // Crear grid de cámaras y players
        createCameraGrid(activeCameras);
        activeCameras.forEach(cam => initVideoPlayer(cam));

        // Mostrar dashboard, ocultar selector (ANTES de initMap para que el DOM tenga tamaño)
        document.getElementById('mode-selector').classList.add('hidden');
        document.getElementById('dashboard-content').classList.remove('hidden');

        // Mapa solo en modo live (después de que el dashboard sea visible)
        const mapSection = document.getElementById('map-section');
        mapSection.classList.remove('hidden');
        // Delay para que el contenedor del mapa tenga dimensiones reales
        setTimeout(() => initMap(activeCameras), 200);

        // Iniciar auto-refresh
        startAutoRefresh();

        if (window.loadingFallbackTimeout) clearTimeout(window.loadingFallbackTimeout);
        window.loadingFallbackTimeout = setTimeout(() => {
            hideLoadingOverlay();
        }, 30000);

    } catch (err) {
        console.error('[StartMode]', err);
        hideLoadingOverlay();
        alert('Error de conexión al iniciar el modo. ¿El servidor está corriendo?');
    }
}


async function goBackToMenu() {
    showLoadingOverlay('Deteniendo procesos...');

    try {
        await fetch('/api/stop', { method: 'POST' });
    } catch (err) {
        console.error('[Stop]', err);
    }

    // Destruir reproductores HLS
    Object.values(hlsPlayers).forEach(hls => {
        try { hls.destroy(); } catch {}
    });
    hlsPlayers = {};

    // Pausar y limpiar todos los <video>
    document.querySelectorAll('#camera-grid video').forEach(v => {
        v.pause();
        v.removeAttribute('src');
        v.load();
    });

    // Destruir mapa
    if (leafletMap) {
        leafletMap.remove();
        leafletMap = null;
        heatLayer = null;
        cameraMarkers = {};
    }

    // Limpiar timers
    stopAutoRefresh();

    // Resetear estado del frontend
    resetFrontendState();

    // Mostrar selector, ocultar dashboard
    document.getElementById('dashboard-content').classList.add('hidden');
    document.getElementById('mode-selector').classList.remove('hidden');

    currentMode = null;
    activeCameras = [];

    hideLoadingOverlay();
}


// FRONTEND STATE RESET

function resetFrontendState() {
    alertCount = 0;
    selectedCameraId = null;
    perCameraMetrics = {};

    // Contadores a 0
    updateCounter('compliance-rate', 0);
    updateCounter('riders-with-helmet', 0);
    updateCounter('riders-without-helmet', 0);
    updateCounter('alert-count', 0);

    // Barra de compliance
    const bar = document.getElementById('compliance-bar');
    if (bar) bar.style.width = '0%';

    // Vaciar alertas
    const alertsContainer = document.getElementById('alerts-container');
    if (alertsContainer) {
        alertsContainer.innerHTML = `
            <div class="text-center text-gray-500 py-8">
                <svg class="w-12 h-12 mx-auto mb-2 opacity-50" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                        d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z">
                    </path>
                </svg>
                <p class="text-sm">No hay alertas aún</p>
            </div>`;
    }

    // Vaciar grid de cámaras
    const grid = document.getElementById('camera-grid');
    if (grid) grid.innerHTML = '';

    // Label de cámara seleccionada
    const label = document.getElementById('selected-camera-label');
    if (label) label.textContent = 'Todas las cámaras';

    // Cerrar modal y destruir gráficos si estaban abiertos
    closeAlertModal();
    if (chartHourly) { chartHourly.destroy(); chartHourly = null; }
    if (chartCamera) { chartCamera.destroy(); chartCamera = null; }
    switchTab('monitoring');
}


// AUTO-REFRESH TIMERS

function startAutoRefresh() {
    stopAutoRefresh(); // Limpiar previos por si acaso
    metricsInterval = setInterval(updateAccumulatedMetrics, 5000);
    heatmapInterval = setInterval(updateHeatmap, 10000);
}

function stopAutoRefresh() {
    if (metricsInterval) { clearInterval(metricsInterval); metricsInterval = null; }
    if (heatmapInterval) { clearInterval(heatmapInterval); heatmapInterval = null; }
}


// LOADING OVERLAY

function showLoadingOverlay(text) {
    const overlay = document.getElementById('loading-overlay');
    const textEl  = document.getElementById('loading-text');
    if (textEl) textEl.textContent = text || 'Cargando...';
    overlay.classList.remove('hidden');
}

function hideLoadingOverlay() {
    document.getElementById('loading-overlay').classList.add('hidden');
}


// CAMERA GRID

function createCameraGrid(cameras) {
    const grid = document.getElementById('camera-grid');
    grid.innerHTML = '';
    cameras.forEach(cam => {
        const card = document.createElement('div');
        card.className = 'camera-card';
        card.id = `camera-card-${cam.id}`;
        card.onclick = () => selectCamera(cam.id);
        
        let mediaTag = `<video id="video-${cam.id}" muted autoplay playsinline webkit-playsinline></video>`;
        if (cam.source.includes('youtube.com') || cam.source.includes('youtu.be')) {
            const match = cam.source.match(/(?:youtu\.be\/|youtube\.com\/(?:embed\/|v\/|watch\?v=|watch\?.+&v=))([\w-]{11})/);
            if (match) {
                mediaTag = `<iframe id="video-${cam.id}" class="w-full h-full object-cover pointer-events-none" src="https://www.youtube.com/embed/${match[1]}?autoplay=1&mute=1&controls=0&disablekb=1&modestbranding=1&playsinline=1" frameborder="0" allow="autoplay; encrypted-media" allowfullscreen></iframe>`;
            }
        }

        card.innerHTML = `
            ${mediaTag}
            <div class="camera-bottom-overlay">
                <div class="camera-label">
                    <span class="cam-name" title="${cam.name}">Cam ${cam.id} · ${cam.name}</span>
                    <span class="cam-status" id="cam-status-${cam.id}">
                        <span class="dot"></span><span>Cargando</span>
                    </span>
                </div>
                <div class="cam-mini-metrics" id="mini-metrics-${cam.id}">
                    <span class="text-green-400 font-semibold" id="mini-con-${cam.id}">0</span>
                    <span class="text-gray-400 text-xs"> con </span>
                    <span class="text-red-400 font-semibold" id="mini-sin-${cam.id}">0</span>
                    <span class="text-gray-400 text-xs"> sin </span>
                    <span class="text-blue-300 font-semibold" id="mini-rate-${cam.id}">–</span>
                    <span class="text-gray-400 text-xs">%</span>
                </div>
            </div>
        `;
        grid.appendChild(card);
    });
}


// VIDEO PLAYERS

function initVideoPlayer(cam) {
    if (cam.source.includes('youtube.com') || cam.source.includes('youtu.be')) {
        const statusEl = document.getElementById(`cam-status-${cam.id}`);
        if (statusEl) statusEl.innerHTML = '<span class="dot"></span><span>En vivo</span>';
        return;
    }

    const video    = document.getElementById(`video-${cam.id}`);
    const statusEl = document.getElementById(`cam-status-${cam.id}`);
    if (!video) return;

    video.muted      = true;
    video.playsInline = true;

    // HLS
    if (Hls.isSupported()) {
        const hls = new Hls({
            enableWorker: true, lowLatencyMode: false,
            backBufferLength: 60, maxBufferLength: 120, maxMaxBufferLength: 240,
            startPosition: -1, liveDurationInfinity: true,
            fragLoadingMaxRetry: 6, fragLoadingRetryDelay: 1000, manifestLoadingMaxRetry: 3
        });
        hls.loadSource(cam.source);
        hls.attachMedia(video);
        hls.on(Hls.Events.MANIFEST_PARSED, () => {
            video.play().catch(() => {});
            if (statusEl) statusEl.innerHTML = '<span class="dot"></span><span>En vivo</span>';
        });
        hls.on(Hls.Events.ERROR, (_, data) => {
            if (!data.fatal) return;
            if (statusEl) { statusEl.classList.add('error'); statusEl.innerHTML = '<span class="dot"></span><span>Error</span>'; }
            if (data.type === Hls.ErrorTypes.NETWORK_ERROR) setTimeout(() => hls.startLoad(), 3000);
            else if (data.type === Hls.ErrorTypes.MEDIA_ERROR) hls.recoverMediaError();
        });
        hlsPlayers[cam.id] = hls;
    } else if (video.canPlayType('application/vnd.apple.mpegurl')) {
        video.src = cam.source;
        video.addEventListener('loadedmetadata', () => {
            video.play().catch(() => {});
            if (statusEl) statusEl.innerHTML = '<span class="dot"></span><span>En vivo</span>';
        });
    }
}


// CAMERA SELECTION

function selectCamera(camId) {
    selectedCameraId = selectedCameraId === camId ? null : camId;
    const label = document.getElementById('selected-camera-label');
    if (label) {
        if (selectedCameraId) {
            const cam = activeCameras.find(c => c.id === camId);
            label.textContent = cam ? cam.name : `Cam ${camId}`;
        } else {
            label.textContent = 'Todas las cámaras';
        }
    }
    document.querySelectorAll('.camera-card').forEach(c => c.classList.remove('selected'));
    if (selectedCameraId) document.getElementById(`camera-card-${selectedCameraId}`)?.classList.add('selected');
    updateAccumulatedMetrics();
}


// MAP

function initMap(cameras) {
    const liveCams = cameras;
    if (!liveCams.length) return;

    // Si ya existe un mapa, destruirlo
    if (leafletMap) {
        leafletMap.remove();
        leafletMap = null;
        heatLayer = null;
        cameraMarkers = {};
    }

    const avgLat = liveCams.reduce((s, c) => s + c.lat, 0) / liveCams.length;
    const avgLng = liveCams.reduce((s, c) => s + c.lng, 0) / liveCams.length;

    leafletMap = L.map('map', { zoomControl: true, attributionControl: false }).setView([avgLat, avgLng], 5);
    L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png?key=cb1_3l84_1_44abfe8ea113881895fea19b', { maxZoom: 19 }).addTo(leafletMap);

    liveCams.forEach(cam => {
        const marker = L.circleMarker([cam.lat, cam.lng], {
            radius: 8, fillColor: '#6366f1', color: '#818cf8', weight: 2, opacity: 0.9, fillOpacity: 0.7
        }).addTo(leafletMap);
        marker.bindPopup(`
            <div class="popup-title">${cam.name}</div>
            <div class="popup-stat"><span class="label">Con casco</span><span class="value green" id="popup-con-${cam.id}">0</span></div>
            <div class="popup-stat"><span class="label">Sin casco</span><span class="value red" id="popup-sin-${cam.id}">0</span></div>
        `, { closeButton: false });
        cameraMarkers[cam.id] = marker;
    });

    heatLayer = L.heatLayer([], {
        radius: 40, blur: 25, maxZoom: 17, max: 1.0,
        gradient: { 0.0: '#1e3a5f', 0.3: '#3b82f6', 0.5: '#eab308', 0.7: '#f97316', 1.0: '#ef4444' }
    }).addTo(leafletMap);

    leafletMap.fitBounds(L.latLngBounds(liveCams.map(c => [c.lat, c.lng])).pad(0.3));
    updateHeatmap();
    setTimeout(() => leafletMap.invalidateSize(), 500);
}

function updateHeatmap() {
    fetch(`/api/map/heatmap?range=${currentTimeFilter}`)
        .then(r => r.json())
        .then(data => {
            if (!heatLayer) return;
            heatLayer.setLatLngs(data.filter(d => d.intensity > 0).map(d => [d.lat, d.lng, d.intensity]));
            data.forEach(d => {
                const marker = cameraMarkers[d.camera_id];
                if (!marker) return;
                let fc = '#6366f1';
                if (d.sin_casco > 10) fc = '#ef4444';
                else if (d.sin_casco > 5) fc = '#f97316';
                else if (d.sin_casco > 0) fc = '#eab308';
                marker.setStyle({ fillColor: fc, color: fc });
                const popup = marker.getPopup();
                if (popup) {
                    const el = document.createElement('div');
                    el.innerHTML = popup.getContent();
                    const q = id => el.querySelector(`#${id}`);
                    if (q(`popup-con-${d.camera_id}`)) q(`popup-con-${d.camera_id}`).textContent = d.con_casco;
                    if (q(`popup-sin-${d.camera_id}`)) q(`popup-sin-${d.camera_id}`).textContent = d.sin_casco;
                    popup.setContent(el.innerHTML);
                }
            });
        })
        .catch(err => console.error('[Heatmap]', err));
}


// TIME FILTER

function changeTimeFilter(timeRange) {
    currentTimeFilter = timeRange;
    document.querySelectorAll('.time-filter-btn').forEach(btn => {
        btn.classList.remove('bg-blue-500/30', 'border-blue-500/50', 'text-blue-300');
        btn.classList.add('bg-white/10', 'border-white/20', 'text-gray-400');
    });
    const btn = document.getElementById(`filter-${timeRange}`);
    btn.classList.remove('bg-white/10', 'border-white/20', 'text-gray-400');
    btn.classList.add('bg-blue-500/30', 'border-blue-500/50', 'text-blue-300');
    updateAccumulatedMetrics();
    updateHeatmap();
}


// MÉTRICAS GLOBALES

function updateAccumulatedMetrics() {
    if (!currentMode) return;
    const url = `/api/metrics/${currentTimeFilter}` +
                (selectedCameraId ? `?camera_id=${selectedCameraId}` : '');
    fetch(url)
        .then(r => r.json())
        .then(data => {
            updateCounter('riders-with-helmet',    data.riders_with_helmet);
            updateCounter('riders-without-helmet', data.riders_without_helmet);
            const rate = data.compliance_rate || 0;
            updateCounter('compliance-rate', rate.toFixed(0));
            const bar = document.getElementById('compliance-bar');
            if (bar) {
                bar.style.width = `${rate}%`;
                bar.className = 'h-2 rounded-full transition-all duration-500 bg-gradient-to-r ' +
                    (rate >= 80 ? 'from-green-500 to-emerald-400' :
                     rate >= 50 ? 'from-yellow-500 to-orange-400' :
                                  'from-red-500 to-orange-400');
            }
        })
        .catch(err => console.error('[Metrics]', err));
}

function updateCounter(id, val) {
    const el = document.getElementById(id);
    if (!el) return;
    const str = String(val);
    if (el.textContent !== str) {
        el.textContent = str;
        el.classList.add('counter-update');
        setTimeout(() => el.classList.remove('counter-update'), 300);
    }
}


// WEBSOCKET

socket.on('connect',    () => updateConnectionStatus(true));
socket.on('disconnect', () => updateConnectionStatus(false));

socket.on('metrics_update', data => {
    if (!currentMode) return;
    // Panel mini por cámara
    const id = data.camera_id;
        if (id != null) {
            const con  = data.riders_with_helmet    || 0;
            const sin  = data.riders_without_helmet || 0;
            const rate = data.compliance_rate       || 0;
            const conEl  = document.getElementById(`mini-con-${id}`);
            const sinEl  = document.getElementById(`mini-sin-${id}`);
            const rateEl = document.getElementById(`mini-rate-${id}`);
            if (conEl)  conEl.textContent  = con;
            if (sinEl)  sinEl.textContent  = sin;
            if (rateEl) rateEl.textContent = rate.toFixed(0);
        }
    // Panel global
    updateAccumulatedMetrics();
});

socket.on('violation_detected', data => {
    if (!currentMode) return;
    
    addAlert(data);
    playAlertSound();
    const card = document.getElementById(`camera-card-${data.camera_id}`);
    if (card) {
        card.classList.remove('violation-flash');
        void card.offsetWidth;
        card.classList.add('violation-flash');
        setTimeout(() => card.classList.remove('violation-flash'), 1500);
    }
    updateHeatmap();
    if (activeTab === 'dashboard') {
        if (typeof fetchDashboardStats === 'function') fetchDashboardStats();
    }
});

socket.on('camera_finished', data => {
    if (!currentMode) return;
    const statusEl = document.getElementById(`cam-status-${data.camera_id}`);
    if (statusEl) {
        statusEl.innerHTML = '<span class="dot" style="background:#f59e0b;animation:none"></span><span>Finalizado</span>';
    }
    console.log(`[WS] Cam ${data.camera_id} (${data.camera_name}) terminó`);
});

socket.on('camera_error', data => {
    if (!currentMode) return;
    const statusEl = document.getElementById(`cam-status-${data.cam_id}`);
    if (statusEl) {
        statusEl.classList.add('error');
        statusEl.innerHTML = '<span class="dot" style="background:#ef4444;animation:none"></span><span class="text-red-400">Error / Desconectado</span>';
    }
    console.log(`[WS] Cam ${data.cam_id} error: ${data.message}`);
});

socket.on('camera_reconnecting', data => {
    if (!currentMode) return;
    const statusEl = document.getElementById(`cam-status-${data.cam_id}`);
    if (statusEl) {
        statusEl.classList.remove('error');
        statusEl.innerHTML = '<span class="dot" style="background:#facc15;"></span><span class="text-yellow-400">Reconectando...</span>';
    }
});

socket.on('camera_processing', data => {
    if (!currentMode) return;
    const statusEl = document.getElementById(`cam-status-${data.cam_id}`);
    if (statusEl) {
        statusEl.classList.remove('error');
        statusEl.innerHTML = '<span class="dot"></span><span>En vivo</span>';
    }
    const overlay = document.getElementById('loading-overlay');
    if (overlay && !overlay.classList.contains('hidden')) {
        hideLoadingOverlay();
        if (window.loadingFallbackTimeout) {
            clearTimeout(window.loadingFallbackTimeout);
            window.loadingFallbackTimeout = null;
        }
    }
});

function updateConnectionStatus(connected) {
    const el = document.getElementById('ws-status');
    if (!el) return;
    el.textContent = connected ? '● Conectado' : '● Desconectado';
    el.className   = connected ? 'text-green-400' : 'text-red-400';
}

function addAlert(alert) {
    const container = document.getElementById('alerts-container');
    if (!container) return;
    if (container.querySelector('.text-center')) container.innerHTML = '';

    const div = document.createElement('div');
    div.className = 'bg-red-500/10 border border-red-500/30 rounded-lg p-3 fade-in cursor-pointer hover:bg-red-500/20 hover:border-red-500/60 transition-all alert-card-interactive';
    div.onclick = () => openAlertModal(alert);
    const ts   = new Date(alert.timestamp * 1000).toLocaleTimeString('es-ES');
    const conf = alert.confidence ? (alert.confidence * 100).toFixed(1) : 'N/A';
    const cam  = alert.camera_name
        ? `<span class="text-blue-400">Cam ${alert.camera_id}: ${alert.camera_name}</span> · ` : '';

    div.innerHTML = `
        <div class="flex items-start space-x-3">
            <div class="w-10 h-10 bg-red-500/20 rounded-lg flex items-center justify-center flex-shrink-0">
                <svg class="w-5 h-5 text-red-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                          d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"/>
                </svg>
            </div>
            <div class="flex-1 min-w-0">
                <div class="flex items-center justify-between mb-1">
                    <span class="text-sm font-semibold text-red-400">Sin casco</span>
                    <span class="text-xs text-gray-400">${ts}</span>
                </div>
                <p class="text-xs text-gray-400">${cam}Confianza: ${conf}%</p>
            </div>
        </div>`;

    container.insertBefore(div, container.firstChild);
    alertCount++;
    updateCounter('alert-count', alertCount);
    const all = container.querySelectorAll('.fade-in');
    if (all.length > 20) all[all.length - 1].remove();
}

// AUDIO NOTIFICATIONS & MUTE TOGGLE (F16-F19)

function unlockAudioContext() {
    if (isAudioUnlocked) return;
    try {
        const AudioCtx = window.AudioContext || window.webkitAudioContext;
        if (AudioCtx && !audioContext) {
            audioContext = new AudioCtx();
        }
        if (audioContext && audioContext.state === 'suspended') {
            audioContext.resume();
        }
        isAudioUnlocked = true;
    } catch (e) {
        console.warn('[Audio] AudioContext unlock failed', e);
    }
}

function playSynthesizedChime() {
    try {
        const AudioCtx = window.AudioContext || window.webkitAudioContext;
        if (!audioContext && AudioCtx) {
            audioContext = new AudioCtx();
        }
        if (!audioContext) return;
        if (audioContext.state === 'suspended') {
            audioContext.resume();
        }
        const now = audioContext.currentTime;
        const osc = audioContext.createOscillator();
        const gain = audioContext.createGain();
        osc.type = 'sine';
        osc.frequency.setValueAtTime(587.33, now); // D5 note
        osc.frequency.exponentialRampToValueAtTime(880.0, now + 0.08); // A5 note
        gain.gain.setValueAtTime(0.15, now);
        gain.gain.exponentialRampToValueAtTime(0.001, now + 0.25);
        osc.connect(gain);
        gain.connect(audioContext.destination);
        osc.start(now);
        osc.stop(now + 0.25);
    } catch (err) {
        console.warn('[Audio] Chime synthesis error', err);
    }
}

function playAlertSound() {
    if (alertSoundMuted) return;
    unlockAudioContext();
    const sound = document.getElementById('alert-sound');
    if (sound) {
        sound.currentTime = 0;
        const playPromise = sound.play();
        if (playPromise !== undefined) {
            playPromise.catch(() => {
                playSynthesizedChime();
            });
        }
    } else {
        playSynthesizedChime();
    }
}

function toggleAudioMute() {
    alertSoundMuted = !alertSoundMuted;
    localStorage.setItem('alertSoundMuted', String(alertSoundMuted));
    localStorage.setItem('helmet_alert_muted', String(alertSoundMuted));
    updateAudioToggleUI();
}

function updateAudioToggleUI() {
    const btn = document.getElementById('btn-audio-toggle');
    const icon = document.getElementById('audio-toggle-icon');
    const text = document.getElementById('audio-toggle-text');
    if (!btn) return;
    if (alertSoundMuted) {
        btn.setAttribute('aria-label', 'Activar sonido de alertas (Silenciado)');
        btn.setAttribute('title', 'Activar sonido de alertas');
        if (icon) icon.textContent = '🔇';
        if (text) text.textContent = 'Silenciado';
        btn.classList.add('bg-red-500/20', 'border-red-500/40');
        btn.classList.remove('bg-white/10', 'border-white/10');
    } else {
        btn.setAttribute('aria-label', 'Silenciar alertas de audio (Activo)');
        btn.setAttribute('title', 'Silenciar sonido de alertas');
        if (icon) icon.textContent = '🔔';
        if (text) text.textContent = 'Sonido';
        btn.classList.remove('bg-red-500/20', 'border-red-500/40');
        btn.classList.add('bg-white/10', 'border-white/10');
    }
}

// ACTIONABLE ALERTS & MODAL (F10-F15)

function openAlertModal(alert) {
    if (!alert) return;
    const modal = document.getElementById('alert-modal');
    if (!modal) return;
    const img = document.getElementById('modal-crop-img');
    const fallback = document.getElementById('modal-crop-fallback');

    // Safe textContent assignment to prevent XSS (F13, test_r1_b04)
    const camEl = document.getElementById('modal-camera');
    if (camEl) camEl.textContent = alert.camera_name ? `Cam ${alert.camera_id}: ${alert.camera_name}` : `Cam ${alert.camera_id || '?'}`;
    const camInfoEl = document.getElementById('modal-camera-info');
    if (camInfoEl) camInfoEl.textContent = alert.camera_name ? `Cam ${alert.camera_id}: ${alert.camera_name}` : `Cam ${alert.camera_id || '?'}`;

    const ts = alert.timestamp ? new Date(alert.timestamp * 1000).toLocaleTimeString('es-ES') : '--:--:--';
    const timeEl = document.getElementById('modal-time');
    if (timeEl) timeEl.textContent = ts;
    const timeInfoEl = document.getElementById('modal-timestamp-info');
    if (timeInfoEl) timeInfoEl.textContent = ts;

    const statusText = alert.type === 'sin_casco' || !alert.type ? 'Sin casco' : alert.type;
    const statusEl = document.getElementById('modal-status');
    if (statusEl) statusEl.textContent = statusText;
    const statusInfoEl = document.getElementById('modal-status-info');
    if (statusInfoEl) statusInfoEl.textContent = statusText;

    const conf = alert.confidence ? `${(alert.confidence * 100).toFixed(1)}%` : 'N/A';
    const confEl = document.getElementById('modal-confidence');
    if (confEl) confEl.textContent = conf;
    const confInfoEl = document.getElementById('modal-conf-info');
    if (confInfoEl) confInfoEl.textContent = conf;

    // Crop image handling (F12, F15, test_r1_b03)
    const rawCrop = alert.crop_url || alert.crop_image || alert.crop_path || '';
    let cropUrl = rawCrop;
    if (cropUrl && !cropUrl.startsWith('http') && !cropUrl.startsWith('/')) {
        cropUrl = `/${cropUrl}`;
    }

    if (img && fallback) {
        if (cropUrl) {
            img.classList.remove('hidden');
            fallback.classList.add('hidden');
            img.src = cropUrl;
        } else {
            img.classList.add('hidden');
            fallback.classList.remove('hidden');
        }
    }

    modal.classList.remove('hidden');
}

function closeAlertModal() {
    const modal = document.getElementById('alert-modal');
    if (!modal) return;
    modal.classList.add('hidden');
    const img = document.getElementById('modal-crop-img');
    if (img) img.src = '';
}

function handleModalImageError() {
    const img = document.getElementById('modal-crop-img');
    const fallback = document.getElementById('modal-crop-fallback');
    if (img) img.classList.add('hidden');
    if (fallback) fallback.classList.remove('hidden');
}

// Backdrop click outside dialog to close modal (F14, test_r1_06)
const alertModalEl = document.getElementById('alert-modal');
if (alertModalEl) {
    alertModalEl.addEventListener('click', e => {
        if (e.target === alertModalEl) {
            closeAlertModal();
        }
    });
}

// Escape key to dismiss modal (F14, test_r1_06, test_comb_09)
document.addEventListener('keydown', e => {
    if (e.key === 'Escape') {
        closeAlertModal();
    }
});

// DASHBOARD & ANALYTICS (F22-F27)

function switchTab(tab) {
    activeTab = tab;
    const monitoringView = document.getElementById('monitoring-view');
    const dashboardView  = document.getElementById('dashboard-view');
    const tabMonitoring  = document.getElementById('tab-monitoring');
    const tabDashboard   = document.getElementById('tab-dashboard');

    if (tab === 'dashboard') {
        if (monitoringView) monitoringView.classList.add('hidden');
        if (dashboardView) dashboardView.classList.remove('hidden');
        if (tabMonitoring) {
            tabMonitoring.classList.remove('active', 'bg-blue-600/30', 'text-blue-400', 'border-blue-500/40');
            tabMonitoring.classList.add('text-gray-400', 'border-transparent');
            tabMonitoring.setAttribute('aria-selected', 'false');
        }
        if (tabDashboard) {
            tabDashboard.classList.add('active', 'bg-blue-600/30', 'text-blue-400', 'border-blue-500/40');
            tabDashboard.classList.remove('text-gray-400', 'border-transparent');
            tabDashboard.setAttribute('aria-selected', 'true');
        }
        fetchDashboardStats();
    } else {
        if (dashboardView) dashboardView.classList.add('hidden');
        if (monitoringView) monitoringView.classList.remove('hidden');
        if (tabDashboard) {
            tabDashboard.classList.remove('active', 'bg-blue-600/30', 'text-blue-400', 'border-blue-500/40');
            tabDashboard.classList.add('text-gray-400', 'border-transparent');
            tabDashboard.setAttribute('aria-selected', 'false');
        }
        if (tabMonitoring) {
            tabMonitoring.classList.add('active', 'bg-blue-600/30', 'text-blue-400', 'border-blue-500/40');
            tabMonitoring.classList.remove('text-gray-400', 'border-transparent');
            tabMonitoring.setAttribute('aria-selected', 'true');
        }
        // Invalidate map layout when returning to monitoring (F21, test_comb_05, test_r5_b04)
        if (leafletMap) leafletMap.invalidateSize();
    }
}

async function fetchDashboardStats() {
    try {
        let res = await fetch('/api/stats/dashboard');
        if (res.status === 404) {
            res = await fetch('/api/dashboard/stats');
        }
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        const summary = data.summary || data;

        // Update KPI metrics
        const totalViolations = summary.total_violations != null ? summary.total_violations : 0;
        const totalDetections = summary.total_detections != null ? summary.total_detections : 0;
        const complianceRate  = summary.compliance_rate != null ? Number(summary.compliance_rate) : 0;

        const violEl = document.getElementById('stat-total-violations');
        if (violEl) violEl.textContent = totalViolations;
        const dashViolEl = document.getElementById('dash-total-violations');
        if (dashViolEl && !violEl) dashViolEl.textContent = totalViolations;
        const dashInfEl = document.getElementById('dash-total-infractions');
        if (dashInfEl) dashInfEl.textContent = totalViolations;

        const detEl = document.getElementById('stat-total-detections');
        if (detEl) detEl.textContent = totalDetections;
        const dashDetEl = document.getElementById('dash-total-detections');
        if (dashDetEl && !detEl) dashDetEl.textContent = totalDetections;

        const compEl = document.getElementById('stat-compliance-rate');
        if (compEl) compEl.textContent = complianceRate.toFixed(1);
        const dashCompEl = document.getElementById('dash-compliance-rate');
        if (dashCompEl && !compEl) dashCompEl.textContent = `${complianceRate.toFixed(1)}%`;

        renderDashboardCharts(data);
    } catch (err) {
        console.error('[DashboardStats]', err);
    }
}

function renderDashboardCharts(data) {
    if (typeof Chart === 'undefined') {
        console.warn('[Dashboard] Chart.js is not loaded yet');
        return;
    }

    // Safely destroy existing charts before recreation (F25, F26, test_r2_b05)
    if (chartHourly) {
        chartHourly.destroy();
        chartHourly = null;
    }
    if (chartCamera) {
        chartCamera.destroy();
        chartCamera = null;
    }

    // Chart 1: Hourly Violations
    const hourlyCanvas = document.getElementById('chart-hourly');
    if (hourlyCanvas) {
        const hourlyData = data.by_hour || [];
        const hours = hourlyData.map(h => h.hour);
        const counts = hourlyData.map(h => h.violations);

        chartHourly = new Chart(hourlyCanvas, {
            type: 'bar',
            data: {
                labels: hours.length > 0 ? hours : ['Sin datos'],
                datasets: [{
                    label: 'Infracciones',
                    data: counts.length > 0 ? counts : [0],
                    backgroundColor: 'rgba(239, 68, 68, 0.65)',
                    borderColor: '#ef4444',
                    borderWidth: 1.5,
                    borderRadius: 6
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        backgroundColor: 'rgba(15, 23, 42, 0.9)',
                        borderColor: 'rgba(239, 68, 68, 0.3)',
                        borderWidth: 1,
                        padding: 10
                    }
                },
                scales: {
                    x: {
                        grid: { color: 'rgba(255, 255, 255, 0.05)' },
                        ticks: { color: '#94a3b8', font: { size: 11 } }
                    },
                    y: {
                        beginAtZero: true,
                        grid: { color: 'rgba(255, 255, 255, 0.05)' },
                        ticks: { color: '#94a3b8', precision: 0, font: { size: 11 } }
                    }
                }
            }
        });
    }

    // Chart 2: Violations by Camera
    const cameraCanvas = document.getElementById('chart-camera');
    if (cameraCanvas) {
        const cameraData = data.by_camera || [];
        const camLabels = cameraData.map(c => c.camera_name || `Cam ${c.camera_id}`);
        const camCounts = cameraData.map(c => c.violations != null ? c.violations : (c.count != null ? c.count : 0));

        chartCamera = new Chart(cameraCanvas, {
            type: 'bar',
            data: {
                labels: camLabels.length > 0 ? camLabels : ['Sin datos'],
                datasets: [{
                    label: 'Infracciones',
                    data: camCounts.length > 0 ? camCounts : [0],
                    backgroundColor: [
                        'rgba(59, 130, 246, 0.65)',
                        'rgba(168, 85, 247, 0.65)',
                        'rgba(236, 72, 153, 0.65)',
                        'rgba(245, 158, 11, 0.65)'
                    ],
                    borderColor: [
                        '#3b82f6',
                        '#a855f7',
                        '#ec4899',
                        '#f59e0b'
                    ],
                    borderWidth: 1.5,
                    borderRadius: 6
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        backgroundColor: 'rgba(15, 23, 42, 0.9)',
                        borderColor: 'rgba(59, 130, 246, 0.3)',
                        borderWidth: 1,
                        padding: 10
                    }
                },
                scales: {
                    x: {
                        grid: { color: 'rgba(255, 255, 255, 0.05)' },
                        ticks: { color: '#94a3b8', font: { size: 11 } }
                    },
                    y: {
                        beginAtZero: true,
                        grid: { color: 'rgba(255, 255, 255, 0.05)' },
                        ticks: { color: '#94a3b8', precision: 0, font: { size: 11 } }
                    }
                }
            }
        });
    }
}

// EXPORT CSV HANDLER (F27)

async function exportViolationsCSV() {
    const btn = document.getElementById('btn-export-csv');
    const textSpan = document.getElementById('btn-export-csv-text') || btn;
    const originalText = textSpan.textContent;

    if (btn) btn.disabled = true;
    if (textSpan) textSpan.textContent = 'Generando CSV...';

    try {
        let res = await fetch('/api/violations/export');
        if (res.status === 404) {
            res = await fetch('/api/reports/csv');
        }
        if (!res.ok) throw new Error(`HTTP error ${res.status}`);

        const blob = await res.blob();
        const downloadUrl = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = downloadUrl;
        const timestamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-');
        a.download = `reporte_infracciones_${timestamp}.csv`;
        document.body.appendChild(a);
        a.click();
        a.remove();
        window.URL.revokeObjectURL(downloadUrl);
    } catch (err) {
        console.error('[CSV Export]', err);
        alert('Error al exportar el reporte CSV. Por favor verifique el estado del servidor.');
    } finally {
        if (btn) btn.disabled = false;
        if (textSpan) textSpan.textContent = originalText;
    }
}


// VISIBILITY (SOLO HLS)

document.addEventListener('visibilitychange', () => {
    if (document.hidden) return;
    setTimeout(() => {
        // Recuperar HLS (Videos en Vivo)
        Object.values(hlsPlayers).forEach(hls => {
            if (!hls?.media) return;
            hls.media.muted = true;
            
            // Forzar salto al momento exacto en vivo para evitar delay acumulado
            if (currentMode === 'live' && hls.liveSyncPosition !== null) {
                hls.media.currentTime = hls.liveSyncPosition;
            }
            
            try { hls.startLoad(); } catch {}
            if (hls.media.paused) hls.media.play().catch(() => {});
        });

        // Recuperar MP4/archivos locales (por si el navegador los pausó)
        if (currentMode === 'file') {
            document.querySelectorAll('video').forEach(video => {
                if (video.paused && video.readyState >= 2) {
                    video.play().catch(() => {});
                }
            });
        }
        
        // Recuperar iframes de YouTube (evitar que se retrasen al cambiar pestaña)
        if (currentMode === 'live') {
            document.querySelectorAll('iframe[src*="youtube.com"]').forEach(iframe => {
                iframe.src = iframe.src;
            });
        }
    }, 100);
});

async function shutdownSystem() {
    if (!confirm('¿Estás seguro de que querés apagar el sistema por completo?')) return;
    try {
        await fetch('/api/shutdown', { method: 'POST' });
    } catch (e) {
        // ignora el error porque el server cerró la conexión
    }
    document.body.innerHTML = `
        <div class="flex flex-col items-center justify-center min-h-screen bg-black text-white text-center">
            <div class="text-6xl mb-6">🛑</div>
            <h1 class="text-4xl font-bold mb-4">Sistema Apagado</h1>
            <p class="text-gray-400">Puede cerrar esta ventana.</p>
        </div>
    `;
}