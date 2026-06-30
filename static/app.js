// Global Application State
let currentUser = null;
let activeView = 'home';
let token = null;

try {
    token = localStorage.getItem("news_ai_token");
    if (localStorage.getItem("news_ai_user")) {
        currentUser = JSON.parse(localStorage.getItem("news_ai_user"));
    }
} catch (e) {
    console.error("Local storage read blocked:", e);
}

function setSessionToken(t, user = null) {
    token = t;
    currentUser = user;
    try {
        if (t) {
            localStorage.setItem("news_ai_token", t);
            if (user) {
                localStorage.setItem("news_ai_user", JSON.stringify(user));
            }
        } else {
            localStorage.removeItem("news_ai_token");
            localStorage.removeItem("news_ai_user");
        }
    } catch (e) {
        console.error("Local storage write blocked:", e);
    }
    setupUserFooter();
}

let activeChatRecipient = null;
let activeGroupChat = null;
let followingList = [];
let chatLogsInterval = null;
let groupLogsInterval = null;
let activePostsCache = [];
let activeCommentsPostId = null;
let selectedAvatarIndex = 1;
let activeReelIndex = 0;
let reelsCache = [];

// ==========================================================================
// E2EE CRYPTO ENGINE  (Web Crypto API — RSA-OAEP + AES-GCM)
// Private key lives ONLY in localStorage, never sent to server.
// ==========================================================================
const CryptoEngine = {
    // Generate a 2048-bit RSA-OAEP key pair
    async generateKeyPair() {
        return await crypto.subtle.generateKey(
            { name: 'RSA-OAEP', modulusLength: 2048, publicExponent: new Uint8Array([1, 0, 1]), hash: 'SHA-256' },
            true, ['encrypt', 'decrypt']
        );
    },

    // Export public key as JWK string (safe to upload to server)
    async exportPublicKey(publicKey) {
        const jwk = await crypto.subtle.exportKey('jwk', publicKey);
        return JSON.stringify(jwk);
    },

    // Export private key as JWK string (store ONLY in localStorage)
    async exportPrivateKey(privateKey) {
        const jwk = await crypto.subtle.exportKey('jwk', privateKey);
        return JSON.stringify(jwk);
    },

    // Import a public key from JWK string
    async importPublicKey(jwkString) {
        const jwk = typeof jwkString === 'string' ? JSON.parse(jwkString) : jwkString;
        return await crypto.subtle.importKey('jwk', jwk, { name: 'RSA-OAEP', hash: 'SHA-256' }, true, ['encrypt']);
    },

    // Import a private key from JWK string
    async importPrivateKey(jwkString) {
        const jwk = typeof jwkString === 'string' ? JSON.parse(jwkString) : jwkString;
        return await crypto.subtle.importKey('jwk', jwk, { name: 'RSA-OAEP', hash: 'SHA-256' }, true, ['decrypt']);
    },

    // Encrypt a plaintext string for one or more recipients
    // Returns { encryptedText: base64, encryptedKeys: { userId: base64 } }
    async encrypt(plaintext, recipientPublicKeys) {
        // Generate a random AES-256-GCM session key
        const aesKey = await crypto.subtle.generateKey({ name: 'AES-GCM', length: 256 }, true, ['encrypt', 'decrypt']);
        const iv = crypto.getRandomValues(new Uint8Array(12));
        const encoded = new TextEncoder().encode(plaintext);
        const cipherBuffer = await crypto.subtle.encrypt({ name: 'AES-GCM', iv }, aesKey, encoded);

        // Export AES key raw bytes
        const aesRaw = await crypto.subtle.exportKey('raw', aesKey);

        // Combine iv + ciphertext
        const combined = new Uint8Array(iv.length + cipherBuffer.byteLength);
        combined.set(iv, 0);
        combined.set(new Uint8Array(cipherBuffer), iv.length);
        const encryptedText = btoa(String.fromCharCode(...combined));

        // Wrap AES key with each recipient's RSA public key
        const encryptedKeys = {};
        for (const [uid, pubKey] of Object.entries(recipientPublicKeys)) {
            if (!pubKey) continue;
            try {
                const wrappedKey = await crypto.subtle.encrypt({ name: 'RSA-OAEP' }, pubKey, aesRaw);
                encryptedKeys[uid] = btoa(String.fromCharCode(...new Uint8Array(wrappedKey)));
            } catch (e) { console.warn('Failed to wrap key for', uid, e); }
        }
        return { encryptedText, encryptedKeys };
    },

    // Decrypt a message using own private key
    async decrypt(encryptedText, encryptedKeyB64, privateKey) {
        if (!encryptedText || !encryptedKeyB64 || !privateKey) return null;
        try {
            // Unwrap AES key
            const wrappedKeyBytes = Uint8Array.from(atob(encryptedKeyB64), c => c.charCodeAt(0));
            const aesRaw = await crypto.subtle.decrypt({ name: 'RSA-OAEP' }, privateKey, wrappedKeyBytes);
            const aesKey = await crypto.subtle.importKey('raw', aesRaw, { name: 'AES-GCM' }, false, ['decrypt']);

            // Split iv + ciphertext
            const combined = Uint8Array.from(atob(encryptedText), c => c.charCodeAt(0));
            const iv = combined.slice(0, 12);
            const cipher = combined.slice(12);
            const plainBuffer = await crypto.subtle.decrypt({ name: 'AES-GCM', iv }, aesKey, cipher);
            return new TextDecoder().decode(plainBuffer);
        } catch (e) {
            console.warn('Decryption failed:', e);
            return '[🔒 Encrypted — key mismatch or corrupted]';
        }
    }
};

// --- E2EE Key Lifecycle ---
async function ensureKeyPair() {
    let privKeyStr = localStorage.getItem('newsai_private_key');
    let pubKeyStr = localStorage.getItem('newsai_public_key');
    if (!privKeyStr || !pubKeyStr) {
        console.log('[E2EE] Generating new RSA-2048 key pair...');
        const kp = await CryptoEngine.generateKeyPair();
        pubKeyStr = await CryptoEngine.exportPublicKey(kp.publicKey);
        privKeyStr = await CryptoEngine.exportPrivateKey(kp.privateKey);
        localStorage.setItem('newsai_public_key', pubKeyStr);
        localStorage.setItem('newsai_private_key', privKeyStr);
    }
    // Upload public key to server
    try {
        await fetch('/keys/publish', {
            method: 'POST',
            headers: getHeaders(),
            body: JSON.stringify({ public_key_jwk: pubKeyStr })
        });
    } catch (e) { console.warn('[E2EE] Could not upload public key:', e); }
    return privKeyStr;
}

async function getPrivateKey() {
    const privKeyStr = localStorage.getItem('newsai_private_key');
    if (!privKeyStr) return null;
    return await CryptoEngine.importPrivateKey(privKeyStr);
}

async function getRecipientPublicKey(username) {
    try {
        const res = await fetch(`/keys/${username}`, { headers: getHeaders() });
        if (!res.ok) return null;
        const data = await res.json();
        return await CryptoEngine.importPublicKey(data.public_key_jwk);
    } catch { return null; }
}

// Download private key as a .json backup file
function downloadPrivateKey() {
    const privKey = localStorage.getItem('newsai_private_key');
    if (!privKey) { alert('No private key found.'); return; }
    const blob = new Blob([privKey], { type: 'application/json' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `newsai_private_key_${currentUser?.username || 'backup'}.json`;
    a.click();
}

// Helper: Generate a high-end gradient SVG avatar dynamically
function getAvatarUrl(avatarIndex, username = "A") {
    const colors = [
        ["#FF5376", "#FF007F"], // Pink gradient
        ["#00F0FF", "#0072FF"], // Cyan/Blue gradient
        ["#9D00FF", "#BD00FF"], // Purple gradient
        ["#FFB900", "#FF6C00"], // Orange gradient
        ["#00FF87", "#60EFFF"], // Green/Cyan gradient
        ["#FF0055", "#00FFCC"], // Magenta/Turquoise gradient
        ["#7B2CBF", "#5A189A"], // Deep Violet gradient
        ["#00F2FE", "#4FACFE"]  // Soft Ocean gradient
    ];
    const pair = colors[(avatarIndex - 1) % colors.length] || colors[0];
    const initial = username.charAt(0).toUpperCase();
    return `data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100" viewBox="0 0 100 100"><defs><linearGradient id="g_${avatarIndex}" x1="0%" y1="0%" x2="100%" y2="100%"><stop offset="0%" stop-color="${encodeURIComponent(pair[0])}"/><stop offset="100%" stop-color="${encodeURIComponent(pair[1])}"/></linearGradient></defs><circle cx="50" cy="50" r="50" fill="url(%23g_${avatarIndex})"/><text x="50" y="58" font-family="'Outfit', sans-serif" font-weight="bold" font-size="36" fill="%23ffffff" text-anchor="middle">${initial}</text></svg>`;
}

// Helper: Format Date strings
function formatDate(isoString) {
    try {
        const d = new Date(isoString);
        return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }) + 
               ' ' + d.toLocaleDateString([], { month: 'short', day: 'numeric' });
    } catch {
        return isoString;
    }
}

// Helper: Format basic Markdown elements to HTML
function formatMarkdown(text) {
    if (!text) return "";
    return text
        .replace(/^# (.*$)/gim, '<h2 style="font-family: var(--font-heading); font-size: 16px; font-weight: 700; margin-top: 15px; margin-bottom: 8px; color: var(--accent-cyan);">$1</h2>')
        .replace(/^### (.*$)/gim, '<h3 style="font-family: var(--font-heading); font-size: 13px; font-weight: 600; margin-top: 12px; margin-bottom: 4px; color: #fff;">$1</h3>')
        .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
        .replace(/- (.*$)/gim, '<li style="margin-left: 15px; margin-bottom: 4px; color: var(--text-secondary);">$1</li>')
        .replace(/\n/g, '<br>');
}

// Request Headers Builder
function getHeaders() {
    const headers = { 'Content-Type': 'application/json' };
    if (token) {
        headers['Authorization'] = `Bearer ${token}`;
    }
    return headers;
}

const API_BASE = window.location.protocol.startsWith('http') ? '' : 'http://127.0.0.1:8081';
function apiFetch(path, options = {}) {
    return fetch(`${API_BASE}${path}`, options);
}

console.log('NewsAI frontend auth script loaded; API_BASE=', API_BASE);

// Check Authentication Session
async function checkAuth() {
    if (!token) {
        showAuthModal(true);
        return;
    }
    try {
        const response = await apiFetch('/auth/me', { headers: getHeaders() });
        if (response.ok) {
            currentUser = await response.json();
            showAuthModal(false);
            setupUserFooter();
            navigateTo('home');
        } else {
            // Token expired or invalid
            setSessionToken(null);
            showAuthModal(true);
        }
    } catch (e) {
        console.error("Auth check failed:", e);
        showAuthModal(true);
    }
}

// Toggle Auth Modal overlay
function showAuthModal(show) {
    const modal = document.getElementById('auth-modal');
    if (show) {
        modal.style.display = 'flex';
        // Small delay so display:flex renders before opacity transition
        requestAnimationFrame(() => modal.classList.add('active'));
    } else {
        modal.classList.remove('active');
        // Hide completely after CSS transition ends (300ms)
        setTimeout(() => { modal.style.display = 'none'; }, 320);
    }
}

// Setup Logged In User Profile Footer in Sidebar
function setupUserFooter() {
    const footer = document.getElementById('sidebar-user-footer');
    const avatar = document.getElementById('user-footer-avatar');
    const name = document.getElementById('user-footer-name');
    const handle = document.getElementById('user-footer-handle');
    
    if (currentUser) {
        avatar.src = getAvatarUrl(currentUser.avatar_index, currentUser.username);
        name.textContent = currentUser.display_name || currentUser.username;
        handle.textContent = `@${currentUser.username}`;
        footer.style.display = 'flex';
    } else {
        footer.style.display = 'none';
    }
}

// --- SINGLE PAGE ROUTER ---
function navigateTo(viewId) {
    activeView = viewId;
    
    // Deactivate DM logs interval if switching away from messages
    if (viewId !== 'messages' && chatLogsInterval) {
        clearInterval(chatLogsInterval);
        chatLogsInterval = null;
    }
    
    // Set active class in sidebar
    document.querySelectorAll('.app-sidebar .menu-item').forEach(item => {
        if (item.getAttribute('data-view') === viewId) {
            item.classList.add('active');
        } else {
            item.classList.remove('active');
        }
    });

    // Toggle view visibility
    document.querySelectorAll('.view-section').forEach(view => {
        if (view.id === `view-${viewId}`) {
            view.classList.remove('hidden');
        } else {
            view.classList.add('hidden');
        }
    });

    // Route-specific loading actions
    if (viewId === 'home') loadHomeFeed();
    else if (viewId === 'explore') loadExploreGrid();
    else if (viewId === 'reels') loadReelsSwiper();
    else if (viewId === 'messages') { loadDMsSidebar(); loadGroupsSidebar(); }
    else if (viewId === 'admin') loadAdminPanel();
    else if (viewId === 'profile') loadUserProfile(currentUser.username);
}

// Attach Router Event Listeners
document.querySelectorAll('.app-sidebar .menu-item').forEach(item => {
    item.addEventListener('click', () => {
        const view = item.getAttribute('data-view');
        navigateTo(view);
    });
});

document.getElementById('user-footer-profile').addEventListener('click', () => {
    if (currentUser) navigateTo('profile');
});


// --- 1. VIEW: HOME FEED TIMELINE ---
async function loadHomeFeed() {
    const list = document.getElementById('home-posts-list');
    try {
        const response = await fetch('/posts', { headers: getHeaders() });
        if (!response.ok) throw new Error();
        const posts = await response.json();
        activePostsCache = posts;
        
        // Render only verified/published articles in the main timeline
        const feedPosts = posts.filter(p => p.status === 'published');
        
        if (feedPosts.length === 0) {
            list.innerHTML = '<div class="empty-state">No verified stories in the feed. Post a news story under the "Create" tab to start!</div>';
            return;
        }
        
        list.innerHTML = feedPosts.map(post => {
            const scorePercent = (post.confidence_score * 100).toFixed(0) + '%';
            const userAvatar = getAvatarUrl(post.user_id ? ((post.user_id % 8) + 1) : 1, post.username);
            
            return `
                <div class="feed-item" id="feed-post-${post.post_id}">
                    <div class="feed-item-header">
                        <div class="feed-item-user-info" onclick="loadUserProfile('${post.username}')">
                            <img src="${userAvatar}" alt="Avatar" class="avatar-sm">
                            <div>
                                <h4>${post.username} <span class="verified-checkmark">✓</span></h4>
                                <p>${post.source} • ${formatDate(post.created_at)}</p>
                            </div>
                        </div>
                        <span class="badge published">Verified</span>
                    </div>
                    
                    ${post.image_path ? `
                    <div class="feed-item-media">
                        <img src="/posts/${post.post_id}/image" alt="News Image Card">
                        <div class="media-play-overlay" onclick="openReelPlayer('${post.post_id}', '${post.username}', '${post.content.replace(/'/g, "\\'")}', ${post.likes_count})">
                            <div class="play-circle">
                                <svg width="24" height="24" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5V19L19 12L8 5Z"/></svg>
                            </div>
                        </div>
                    </div>
                    ` : `
                    <div class="feed-item-media text-card-media" style="background: linear-gradient(135deg, #181528 0%, #110d21 100%); display: flex; flex-direction: column; justify-content: center; align-items: center; padding: 25px; text-align: center; border-radius: 8px; border: 1px solid var(--border-glass); min-height: 150px; cursor: pointer;" onclick="openPostDetailModal('${post.post_id}')">
                        <span class="text-card-source" style="color: var(--accent-cyan); font-size: 11px; text-transform: uppercase; font-weight: 700; margin-bottom: 8px; letter-spacing: 2px;">📢 ${post.source} ALERT</span>
                        <p class="text-card-content" style="color: #fff; font-size: 15px; font-weight: 600; line-height: 1.4; font-family: var(--font-heading);">${post.content}</p>
                    </div>
                    `}
                    
                    <div class="feed-item-actions-bar">
                        <button class="action-icon-btn" onclick="toggleLike('${post.post_id}', this)">
                            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 14c1.49-1.46 3-3.21 3-5.5A5.5 5.5 0 0 0 16.5 3c-1.76 0-3 .5-4.5 2-1.5-1.5-2.74-2-4.5-2A5.5 5.5 0 0 0 2 8.5c0 2.3 1.5 4.05 3 5.5l7 7Z"/></svg>
                        </button>
                        <button class="action-icon-btn" onclick="openCommentsDrawer('${post.post_id}')">
                            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"/></svg>
                        </button>
                        <button class="action-icon-btn" onclick="toggleSavePost('${post.post_id}', this)">
                            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m19 21-7-4-7 4V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2v16z"/></svg>
                        </button>
                        
                        ${post.accuracy_percentage !== null ? `
                        <button class="action-icon-btn fact-check-badge" onclick="openPostDetailModal('${post.post_id}')" style="color: ${post.accuracy_percentage >= 80 ? '#00f0ff' : (post.accuracy_percentage >= 50 ? '#ffb700' : '#ff4747')}; border-color: ${post.accuracy_percentage >= 80 ? '#00f0ff' : (post.accuracy_percentage >= 50 ? '#ffb700' : '#ff4747')}40; background: ${post.accuracy_percentage >= 80 ? '#00f0ff' : (post.accuracy_percentage >= 50 ? '#ffb700' : '#ff4747')}10; font-weight: 700; cursor: pointer;" title="Click to view AI Fact-Checking Report">
                            🛡️ AI Checked: ${post.accuracy_percentage}% Accuracy
                        </button>
                        ` : `
                        <button class="action-icon-btn fact-check-badge" title="Verification detail metrics">
                            🛡️ Match: ${scorePercent}
                        </button>
                        `}
                    </div>
                    
                    <div class="feed-item-stats">
                        <span id="like-count-${post.post_id}">${post.likes_count}</span> likes
                    </div>
                    
                    <div class="feed-item-caption">
                        <strong onclick="loadUserProfile('${post.username}')">${post.username}</strong> ${post.content}
                    </div>
                    
                    <span class="view-comments-link" onclick="openCommentsDrawer('${post.post_id}')">
                        View comment thread...
                    </span>
                </div>
            `;
        }).join('');
    } catch {
        list.innerHTML = '<div class="empty-state">Failed to load feed. Make sure the backend server is running!</div>';
    }
    await loadSuggestedUsers();
}

// Suggested Users Recommendations Sidebar Loader
async function loadSuggestedUsers() {
    const container = document.getElementById('suggested-users-container');
    if (!container) return;
    try {
        const response = await fetch('/users', { headers: getHeaders() });
        if (!response.ok) throw new Error();
        const users = await response.json();

        // Exclude current user and take top 5 recommendations
        const filtered = users.filter(u => u.username !== currentUser.username).slice(0, 5);

        if (filtered.length === 0) {
            container.innerHTML = '<div class="empty-state">No recommendations yet.</div>';
            return;
        }

        // Load details for each to get following status
        const rows = await Promise.all(filtered.map(async u => {
            const pRes = await fetch(`/users/${u.username}/profile`, { headers: getHeaders() });
            if (!pRes.ok) return null;
            const profile = await pRes.json();
            const userAvatar = getAvatarUrl(profile.avatar_index, profile.username);
            return `
                <div class="suggested-user-row">
                    <div class="suggested-user-info" onclick="loadUserProfile('${profile.username}')">
                        <img src="${userAvatar}" alt="Avatar" class="avatar-sm">
                        <div class="suggested-user-details">
                            <h4>${profile.display_name || profile.username}</h4>
                            <p>@${profile.username}</p>
                        </div>
                    </div>
                    <button class="btn btn-follow-xs ${profile.is_following ? '' : 'btn-glow'}" 
                            onclick="toggleFollowSuggested('${profile.username}', this)">
                        ${profile.is_following ? 'Following' : 'Follow'}
                    </button>
                </div>
            `;
        }));

        container.innerHTML = rows.filter(Boolean).join('');
    } catch (e) {
        container.innerHTML = '<div class="empty-state">Failed to load suggestions.</div>';
    }
}

async function toggleFollowSuggested(username, btn) {
    try {
        const res = await fetch(`/users/${username}/follow`, {
            method: 'POST',
            headers: getHeaders()
        });
        if (res.ok) {
            const data = await res.json();
            const isFollowing = data.status === 'followed';
            btn.textContent = isFollowing ? 'Following' : 'Follow';
            btn.className = `btn btn-follow-xs ${isFollowing ? '' : 'btn-glow'}`;
            // Refresh profile view stats if open
            if (activeView === 'profile') {
                loadUserProfile(username);
            }
        }
    } catch (e) {
        console.error('Follow failed:', e);
    }
}

// Like Post Toggle
async function toggleLike(postId, button) {
    const isLiked = button.classList.contains('liked');
    const action = isLiked ? 'unlike' : 'like';
    try {
        const response = await fetch(`/posts/${postId}/like?action=${action}`, {
            method: 'POST',
            headers: getHeaders()
        });
        if (response.ok) {
            const data = await response.json();
            button.classList.toggle('liked');
            document.getElementById(`like-count-${postId}`).textContent = data.likes_count;
        }
    } catch (e) {
        console.error(e);
    }
}

// Save/Bookmark Post Toggle
async function toggleSavePost(postId, button) {
    const isSaved = button.classList.contains('saved');
    const method = isSaved ? 'DELETE' : 'POST';
    try {
        const response = await fetch(`/posts/${postId}/save`, {
            method: method,
            headers: getHeaders()
        });
        if (response.ok) {
            button.classList.toggle('saved');
        }
    } catch (e) {
        console.error(e);
    }
}


// --- 2. VIEW: EXPLORE (SEARCH GRID) ---
async function loadExploreGrid(query = '') {
    const grid = document.getElementById('explore-posts-grid');
    try {
        const url = query ? `/explore?query=${encodeURIComponent(query)}` : '/posts';
        const response = await fetch(url, { headers: getHeaders() });
        if (!response.ok) throw new Error();
        const posts = await response.json();
        
        const publishedPosts = posts.filter(p => p.status === 'published');
        if (publishedPosts.length === 0) {
            grid.innerHTML = '<div class="empty-state" style="grid-column: 1/-1;">No matching posts found.</div>';
            return;
        }
        
        grid.innerHTML = publishedPosts.map(post => `
            <div class="grid-cell" onclick="openPostDetailModal('${post.post_id}')">
                <img src="/posts/${post.post_id}/image" alt="Grid Thumbnail">
                <div class="grid-overlay-info">
                    <span>❤️ ${post.likes_count}</span>
                    <span>📺 Reel</span>
                </div>
            </div>
        `).join('');
    } catch (e) {
        grid.innerHTML = '<div class="empty-state" style="grid-column: 1/-1;">Failed to load search grid.</div>';
    }
}

// Handle Explore live search input
document.getElementById('explore-search-input').addEventListener('input', (e) => {
    loadExploreGrid(e.target.value.trim());
});


// --- 3. VIEW: REELS (SWIPER VIEWPORT) ---
async function loadReelsSwiper() {
    const video = document.getElementById('reel-swiper-player');
    const likes = document.getElementById('reel-swiper-likes');
    const author = document.getElementById('reel-swiper-author');
    const caption = document.getElementById('reel-swiper-caption');
    const commentsCount = document.getElementById('reel-swiper-comments-count');
    
    try {
        const response = await fetch('/posts', { headers: getHeaders() });
        if (!response.ok) throw new Error();
        const posts = await response.json();
        
        reelsCache = posts.filter(p => p.status === 'published' && p.video_path);
        
        if (reelsCache.length === 0) {
            author.textContent = "@no_reels";
            caption.textContent = "No verified reels compiled yet.";
            video.src = "";
            likes.textContent = "0";
            return;
        }
        
        // Clamp active reel index
        if (activeReelIndex >= reelsCache.length) activeReelIndex = 0;
        if (activeReelIndex < 0) activeReelIndex = reelsCache.length - 1;
        
        const activeReel = reelsCache[activeReelIndex];
        video.src = `/posts/${activeReel.post_id}/video`;
        likes.textContent = activeReel.likes_count;
        author.textContent = `@${activeReel.username}`;
        caption.textContent = activeReel.content;
        
        // Fetch comments count
        const cRes = await fetch(`/posts/${activeReel.post_id}/comments`, { headers: getHeaders() });
        if (cRes.ok) {
            const comments = await cRes.json();
            commentsCount.textContent = comments.length;
        }
        
        video.play().catch(e => console.log("Autoplay prevented:", e));
        
        // Attach click actions on Reels overlay items
        document.getElementById('reel-swiper-like-btn').onclick = async () => {
            const res = await fetch(`/posts/${activeReel.post_id}/like?action=like`, {
                method: 'POST',
                headers: getHeaders()
            });
            if (res.ok) {
                const data = await res.json();
                likes.textContent = data.likes_count;
            }
        };
        
        document.getElementById('reel-swiper-comment-btn').onclick = () => {
            openCommentsDrawer(activeReel.post_id);
        };
        
    } catch (e) {
        console.error("Failed to load reels:", e);
    }
}

// Swiper Next / Prev buttons
document.getElementById('btn-reel-next').addEventListener('click', () => {
    activeReelIndex++;
    loadReelsSwiper();
});

document.getElementById('btn-reel-prev').addEventListener('click', () => {
    activeReelIndex--;
    loadReelsSwiper();
});


// --- 4. VIEW: DIRECT MESSAGES (DMs WINDOW) ---
async function loadDMsSidebar() {
    const list = document.getElementById('dm-users-list');
    try {
        const response = await fetch('/users', { headers: getHeaders() });
        if (!response.ok) throw new Error();
        const users = await response.json();
        
        // Exclude current user from conversation list
        const otherUsers = users.filter(u => u.username !== currentUser.username);
        
        if (otherUsers.length === 0) {
            list.innerHTML = '<div class="empty-state">No other users online yet.</div>';
            return;
        }
        
        list.innerHTML = otherUsers.map(u => {
            const userAvatar = getAvatarUrl(u.avatar_index, u.username);
            const activeClass = (activeChatRecipient && activeChatRecipient.username === u.username) ? 'active' : '';
            return `
                <div class="dm-user-item ${activeClass}" onclick="openChatWith('${u.username}')">
                    <img src="${userAvatar}" alt="Avatar" class="avatar-sm">
                    <div class="dm-user-item-details">
                        <h4>${u.display_name || u.username}</h4>
                        <p>@${u.username}</p>
                    </div>
                </div>
            `;
        }).join('');
    } catch (e) {
        list.innerHTML = '<div class="empty-state">Failed to load direct messaging contacts.</div>';
    }
}

async function openChatWith(username) {
    if (chatLogsInterval) clearInterval(chatLogsInterval);
    
    try {
        const response = await fetch(`/users/${username}/profile`, { headers: getHeaders() });
        if (!response.ok) throw new Error();
        activeChatRecipient = await response.json();
        
        // Transition panel state
        document.getElementById('chat-pane-empty').classList.add('hidden');
        const activePane = document.getElementById('chat-pane-active');
        activePane.classList.remove('hidden');
        
        // Draw Header
        document.getElementById('chat-recipient-avatar').src = getAvatarUrl(activeChatRecipient.avatar_index, activeChatRecipient.username);
        document.getElementById('chat-recipient-name').textContent = activeChatRecipient.display_name || activeChatRecipient.username;
        document.getElementById('chat-recipient-handle').textContent = `@${activeChatRecipient.username}`;
        
        // Setup Follow Button
        const followBtn = document.getElementById('chat-profile-follow-btn');
        followBtn.textContent = activeChatRecipient.is_following ? 'Following' : 'Follow';
        followBtn.className = activeChatRecipient.is_following ? 'btn' : 'btn btn-glow';
        followBtn.onclick = async () => {
            const fRes = await fetch(`/users/${activeChatRecipient.username}/follow`, {
                method: 'POST',
                headers: getHeaders()
            });
            if (fRes.ok) {
                const data = await fRes.json();
                activeChatRecipient.is_following = data.status === 'followed';
                followBtn.textContent = activeChatRecipient.is_following ? 'Following' : 'Follow';
                followBtn.className = activeChatRecipient.is_following ? 'btn' : 'btn btn-glow';
            }
        };

        // Redraw sidebar select background
        loadDMsSidebar();
        
        // Load initial logs
        await loadChatLogs();
        
        // Start polling chat logs every 2 seconds
        chatLogsInterval = setInterval(loadChatLogs, 2000);
        
    } catch (e) {
        console.error("Open chat failed:", e);
    }
}


async function loadChatLogs() {
    if (!activeChatRecipient) return;
    const logsContainer = document.getElementById('chat-logs-container');
    try {
        const response = await fetch(`/messages?with_user=${activeChatRecipient.username}`, { headers: getHeaders() });
        if (!response.ok) throw new Error();
        const messages = await response.json();

        const previousMsgCount = parseInt(logsContainer.dataset.count || '0');
        if (messages.length === previousMsgCount) return; // No new messages
        logsContainer.dataset.count = messages.length;

        const privateKey = await getPrivateKey();

        // Decrypt all messages in parallel
        const decryptedMsgs = await Promise.all(messages.map(async msg => {
            const isSent = msg.sender_id === currentUser.id;
            let text = msg.text || '';
            if (msg.is_encrypted && msg.encrypted_text) {
                const myEncKey = isSent
                    ? msg.encrypted_key_for_sender
                    : msg.encrypted_key_for_recipient;
                text = await CryptoEngine.decrypt(msg.encrypted_text, myEncKey, privateKey) || text;
            }
            return { ...msg, decryptedText: text, isSent };
        }));

        logsContainer.innerHTML = decryptedMsgs.map(msg => `
            <div class="chat-bubble ${msg.isSent ? 'sent' : 'received'}">
                <div>${msg.decryptedText || '<span class="bubble-decrypting">🔒 Decrypting...</span>'}</div>
                <div class="chat-bubble-time">${formatDate(msg.created_at)}${msg.is_encrypted ? ' <span class="chat-bubble-lock">🔒</span>' : ''}</div>
            </div>
        `).join('');

        logsContainer.scrollTop = logsContainer.scrollHeight;
    } catch (e) { console.error(e); }
}

// Send E2EE DM
document.getElementById('chat-send-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    if (!activeChatRecipient) return;
    const input = document.getElementById('chat-message-input');
    const text = input.value.trim();
    if (!text) return;
    input.value = '';

    try {
        // Fetch recipient's public key
        const recipientPubKey = await getRecipientPublicKey(activeChatRecipient.username);
        const myPubKeyStr = localStorage.getItem('newsai_public_key');
        const myPubKey = myPubKeyStr ? await CryptoEngine.importPublicKey(myPubKeyStr) : null;

        let body;
        if (recipientPubKey && myPubKey) {
            // Encrypt for both sender (self-read) and recipient
            const keys = {
                [currentUser.id]: myPubKey,
                [activeChatRecipient.id]: recipientPubKey
            };
            const { encryptedText, encryptedKeys } = await CryptoEngine.encrypt(text, keys);
            body = {
                recipient_username: activeChatRecipient.username,
                encrypted_text: encryptedText,
                encrypted_key_for_sender: encryptedKeys[currentUser.id],
                encrypted_key_for_recipient: encryptedKeys[activeChatRecipient.id],
            };
        } else {
            // Fallback: plaintext (recipient hasn't published a key yet)
            body = { recipient_username: activeChatRecipient.username, text };
        }

        const res = await fetch('/messages', { method: 'POST', headers: getHeaders(), body: JSON.stringify(body) });
        if (res.ok) await loadChatLogs();
    } catch (e) { console.error('Send failed:', e); }
});


// ==========================================================================
// GROUP CHAT
// ==========================================================================

function switchMsgTab(tab) {
    document.getElementById('tab-dms').classList.toggle('active', tab === 'dms');
    document.getElementById('tab-groups').classList.toggle('active', tab === 'groups');
    document.getElementById('dm-users-list').classList.toggle('hidden', tab !== 'dms');
    document.getElementById('groups-list').classList.toggle('hidden', tab !== 'groups');
}

async function loadGroupsSidebar() {
    const list = document.getElementById('groups-list');
    try {
        const res = await fetch('/groups', { headers: getHeaders() });
        if (!res.ok) return;
        const groups = await res.json();
        if (!groups.length) {
            list.innerHTML = '<div class="empty-state">No groups yet. Create one!</div>';
            return;
        }
        list.innerHTML = groups.map(g => `
            <div class="group-item" onclick="openGroupChat('${g.id}')">
                <div class="group-item-icon">👥</div>
                <div class="group-item-info">
                    <div class="group-item-name">${g.name}</div>
                    <div class="group-item-sub">${g.member_ids.length} members · 🔒 E2EE</div>
                </div>
            </div>
        `).join('');
    } catch (e) { console.error(e); }
}

async function openGroupChat(groupId) {
    if (groupLogsInterval) { clearInterval(groupLogsInterval); groupLogsInterval = null; }
    if (chatLogsInterval) { clearInterval(chatLogsInterval); chatLogsInterval = null; }

    try {
        const res = await fetch(`/groups/${groupId}`, { headers: getHeaders() });
        if (!res.ok) throw new Error();
        activeGroupChat = await res.json();

        // Show group pane
        document.getElementById('chat-pane-empty').classList.add('hidden');
        document.getElementById('chat-pane-active').classList.add('hidden');
        document.getElementById('group-chat-pane').classList.remove('hidden');

        document.getElementById('group-chat-name').textContent = activeGroupChat.name;
        document.getElementById('group-chat-members-count').textContent =
            `${activeGroupChat.member_ids.length} members · 🔒 End-to-End Encrypted`;

        await loadGroupMessages();
        groupLogsInterval = setInterval(loadGroupMessages, 2500);
    } catch (e) { console.error('Open group failed:', e); }
}

async function loadGroupMessages() {
    if (!activeGroupChat) return;
    const logsContainer = document.getElementById('group-logs-container');
    try {
        const res = await fetch(`/groups/${activeGroupChat.id}/messages`, { headers: getHeaders() });
        if (!res.ok) throw new Error();
        const messages = await res.json();

        const previousCount = parseInt(logsContainer.dataset.count || '0');
        if (messages.length === previousCount) return;
        logsContainer.dataset.count = messages.length;

        const privateKey = await getPrivateKey();

        // Build member map for display names
        const memberMap = {};
        (activeGroupChat.members || []).forEach(m => { memberMap[m.id] = m; });

        const decryptedMsgs = await Promise.all(messages.map(async msg => {
            const isSent = msg.sender_id === currentUser.id;
            let text = '';
            if (msg.encrypted_text && msg.encrypted_keys) {
                const myEncKey = msg.encrypted_keys[currentUser.id];
                text = await CryptoEngine.decrypt(msg.encrypted_text, myEncKey, privateKey) || '🔒 Encrypted';
            }
            const senderName = memberMap[msg.sender_id]?.display_name || msg.sender_username || 'Unknown';
            return { ...msg, decryptedText: text, isSent, senderName };
        }));

        logsContainer.innerHTML = decryptedMsgs.map(msg => `
            <div class="chat-bubble ${msg.isSent ? 'sent' : 'received'}">
                ${!msg.isSent ? `<div style="font-size:10px; color:var(--accent-cyan); margin-bottom:2px; font-weight:600;">${msg.senderName}</div>` : ''}
                <div>${msg.decryptedText}</div>
                <div class="chat-bubble-time">${formatDate(msg.created_at)} <span class="chat-bubble-lock">🔒</span></div>
            </div>
        `).join('');
        logsContainer.scrollTop = logsContainer.scrollHeight;
    } catch (e) { console.error(e); }
}

// Send Group E2EE Message
document.getElementById('group-send-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    if (!activeGroupChat) return;
    const input = document.getElementById('group-message-input');
    const text = input.value.trim();
    if (!text) return;
    input.value = '';

    try {
        // Fetch all member public keys
        const members = activeGroupChat.members || [];
        const recipientKeys = {};
        await Promise.all(members.map(async m => {
            if (m.public_key_jwk) {
                try { recipientKeys[m.id] = await CryptoEngine.importPublicKey(m.public_key_jwk); }
                catch (e) { console.warn('Bad public key for', m.username); }
            }
        }));

        const { encryptedText, encryptedKeys } = await CryptoEngine.encrypt(text, recipientKeys);
        await fetch(`/groups/${activeGroupChat.id}/messages`, {
            method: 'POST',
            headers: getHeaders(),
            body: JSON.stringify({ encrypted_text: encryptedText, encrypted_keys: encryptedKeys })
        });
        await loadGroupMessages();
    } catch (e) { console.error('Group send failed:', e); }
});

// New Group Modal
document.getElementById('btn-new-group').addEventListener('click', () => {
    const modal = document.getElementById('new-group-modal');
    modal.style.display = 'flex';
    requestAnimationFrame(() => modal.classList.add('active'));
});

function closeGroupModal() {
    const modal = document.getElementById('new-group-modal');
    modal.classList.remove('active');
    setTimeout(() => { modal.style.display = 'none'; }, 320);
}

document.getElementById('form-create-group').addEventListener('submit', async (e) => {
    e.preventDefault();
    const name = document.getElementById('group-name-input').value.trim();
    const membersRaw = document.getElementById('group-members-input').value;
    const members = membersRaw.split(',').map(s => s.trim()).filter(Boolean);
    const errEl = document.getElementById('group-create-error');
    errEl.classList.add('hidden');

    try {
        const res = await fetch('/groups', {
            method: 'POST',
            headers: getHeaders(),
            body: JSON.stringify({ name, members })
        });
        const data = await res.json();
        if (!res.ok) {
            errEl.textContent = data.detail || 'Failed to create group.';
            errEl.classList.remove('hidden');
            return;
        }
        // Clear form, close modal, refresh groups, open the new group
        document.getElementById('group-name-input').value = '';
        document.getElementById('group-members-input').value = '';
        closeGroupModal();
        switchMsgTab('groups');
        await loadGroupsSidebar();
        await openGroupChat(data.id);
    } catch (err) {
        errEl.textContent = 'Network error. Please try again.';
        errEl.classList.remove('hidden');
    }
});



// --- 5. VIEW: PROFILE PAGE ---
async function loadUserProfile(username) {
    navigateToViewOnly('profile');
    
    const avatar = document.getElementById('profile-avatar-img');
    const usernameHeader = document.getElementById('profile-username-header');
    const idDisplay = document.getElementById('profile-id-display');
    const displayName = document.getElementById('profile-display-name');
    const bioText = document.getElementById('profile-bio-text');
    const postsCount = document.getElementById('profile-posts-count');
    const followersCount = document.getElementById('profile-followers-count');
    const followingCount = document.getElementById('profile-following-count');
    const settingsBtn = document.getElementById('btn-open-settings');
    
    try {
        const response = await fetch(`/users/${username}/profile`, { headers: getHeaders() });
        if (!response.ok) throw new Error();
        const profile = await response.json();
        
        avatar.src = getAvatarUrl(profile.avatar_index, profile.username);
        usernameHeader.textContent = profile.username;
        if (idDisplay) idDisplay.textContent = `ID: ${profile.id}`;
        displayName.textContent = profile.display_name || profile.username;
        bioText.textContent = profile.bio || "No biography details added.";
        postsCount.textContent = profile.posts_count;
        followersCount.textContent = profile.followers_count;
        followingCount.textContent = profile.following_count;
        
        // Control profile edit button visibility (hide if looking at someone else's profile)
        if (username === currentUser.username) {
            settingsBtn.textContent = "Edit Profile";
            settingsBtn.className = "btn";
            settingsBtn.onclick = () => openSettingsModal();
        } else {
            // Render Follow Toggle Button
            settingsBtn.textContent = profile.is_following ? 'Following' : 'Follow';
            settingsBtn.className = profile.is_following ? 'btn' : 'btn btn-glow';
            settingsBtn.onclick = async () => {
                const fRes = await fetch(`/users/${profile.username}/follow`, {
                    method: 'POST',
                    headers: getHeaders()
                });
                if (fRes.ok) {
                    await loadUserProfile(profile.username);
                }
            };
        }
        
        // Load User Posts Grid
        await loadUserPostsGrid(profile.username);
        
        // Tab navigators
        document.getElementById('profile-tab-posts').onclick = async (e) => {
            toggleProfileTab(e.target);
            await loadUserPostsGrid(profile.username);
        };
        
        document.getElementById('profile-tab-saved').onclick = async (e) => {
            toggleProfileTab(e.target);
            await loadUserSavedGrid();
        };
        
    } catch (e) {
        console.error(e);
    }
}

function toggleProfileTab(activeButton) {
    document.querySelectorAll('.profile-tab-btn').forEach(btn => btn.classList.remove('active'));
    activeButton.classList.add('active');
}

async function loadUserPostsGrid(username) {
    const grid = document.getElementById('profile-posts-grid-list');
    try {
        const response = await fetch('/posts', { headers: getHeaders() });
        if (!response.ok) throw new Error();
        const posts = await response.json();
        
        const userPosts = posts.filter(p => p.username === username && p.status === 'published');
        if (userPosts.length === 0) {
            grid.innerHTML = '<div class="empty-state" style="grid-column:1/-1;">No posts created yet.</div>';
            return;
        }
        
        grid.innerHTML = userPosts.map(post => `
            <div class="grid-cell" onclick="openPostDetailModal('${post.post_id}')">
                <img src="/posts/${post.post_id}/image" alt="Post Grid Cell">
                <div class="grid-overlay-info">
                    <span>❤️ ${post.likes_count}</span>
                </div>
            </div>
        `).join('');
    } catch (e) {
        grid.innerHTML = '<div class="empty-state" style="grid-column:1/-1;">Failed to load user posts grid.</div>';
    }
}

async function loadUserSavedGrid() {
    const grid = document.getElementById('profile-posts-grid-list');
    try {
        const response = await fetch('/posts/saved', { headers: getHeaders() });
        if (!response.ok) throw new Error();
        const posts = await response.json();
        
        if (posts.length === 0) {
            grid.innerHTML = '<div class="empty-state" style="grid-column:1/-1;">No saved posts bookmarks yet.</div>';
            return;
        }
        
        grid.innerHTML = posts.map(post => `
            <div class="grid-cell" onclick="openPostDetailModal('${post.post_id}')">
                <img src="/posts/${post.post_id}/image" alt="Saved Grid Cell">
                <div class="grid-overlay-info">
                    <span>❤️ ${post.likes_count}</span>
                </div>
            </div>
        `).join('');
    } catch (e) {
        grid.innerHTML = '<div class="empty-state" style="grid-column:1/-1;">Failed to load bookmarked posts.</div>';
    }
}

// Navigation helper that doesn't trigger tab reload logic
function navigateToViewOnly(viewId) {
    document.querySelectorAll('.app-sidebar .menu-item').forEach(item => {
        if (item.getAttribute('data-view') === viewId) {
            item.classList.add('active');
        } else {
            item.classList.remove('active');
        }
    });

    document.querySelectorAll('.view-section').forEach(view => {
        if (view.id === `view-${viewId}`) {
            view.classList.remove('hidden');
        } else {
            view.classList.add('hidden');
        }
    });
}


// --- 6. VIEW: CREATE POSTS (UPLOADS & SANDBOX) ---
const customPostTab = document.getElementById('btn-create-custom-tab');
const sandboxTab = document.getElementById('btn-create-sandbox-tab');
const paneCreateCustom = document.getElementById('pane-create-custom');
const paneCreateSandbox = document.getElementById('pane-create-sandbox');

customPostTab.addEventListener('click', () => {
    customPostTab.classList.add('active');
    sandboxTab.classList.remove('active');
    paneCreateCustom.classList.remove('hidden');
    paneCreateSandbox.classList.add('hidden');
});

sandboxTab.addEventListener('click', () => {
    sandboxTab.classList.add('active');
    customPostTab.classList.remove('active');
    paneCreateSandbox.classList.remove('hidden');
    paneCreateCustom.classList.add('hidden');
});

// Custom post submit action
document.getElementById('form-create-custom').addEventListener('submit', async (e) => {
    e.preventDefault();
    const content = document.getElementById('custom-post-content').value.trim();
    if (!content) return;
    
    try {
        const response = await fetch(`/posts/create?content=${encodeURIComponent(content)}`, {
            method: 'POST',
            headers: getHeaders()
        });
        if (response.ok) {
            document.getElementById('custom-post-content').value = '';
            alert("Custom post submitted to fact-checking pipeline. We will verify and publish it!");
            navigateTo('home');
        } else {
            const err = await response.json();
            alert("Error publishing post: " + (err.detail || response.statusText));
        }
    } catch {
        alert("Network error publishing post.");
    }
});


// --- 7. VIEW: ADMIN CONTROL PANEL ---
let activeAdminTab = 'all';

async function loadAdminPanel() {
    // 1. Fetch references doc list
    const kbRes = await fetch('/trusted-docs', { headers: getHeaders() });
    const kbCount = document.getElementById('kb-count'); // Wait, kb-count is inside index.html? No, we removed it, but we can verify
    const kbList = document.getElementById('kb-list'); // Wait, let's list references list inside index.html if we want, or verify
    
    // 2. Load Pipeline Queue posts
    await loadAdminQueue();
}

async function loadAdminQueue() {
    const list = document.getElementById('admin-feed-list');
    try {
        const response = await fetch('/posts', { headers: getHeaders() });
        if (!response.ok) throw new Error();
        const posts = await response.json();
        
        const reviewPosts = posts.filter(p => p.status === 'human_review_required');
        
        // Update Admin Red alert counts indicator dots
        const adminDot = document.getElementById('admin-review-count-dot');
        const sidebarDot = document.getElementById('review-count-dot');
        
        if (reviewPosts.length > 0) {
            if (adminDot) adminDot.style.display = 'inline-block';
            if (sidebarDot) sidebarDot.style.display = 'inline-block';
        } else {
            if (adminDot) adminDot.style.display = 'none';
            if (sidebarDot) sidebarDot.style.display = 'none';
        }
        
        const displayPosts = activeAdminTab === 'review' ? reviewPosts : posts;
        
        if (displayPosts.length === 0) {
            list.innerHTML = '<div class="empty-state">No pipeline logs in this list.</div>';
            return;
        }
        
        list.innerHTML = displayPosts.map(post => {
            const requiresReview = post.status === 'human_review_required';
            const scorePercent = (post.confidence_score * 100).toFixed(1) + '%';
            
            return `
                <div class="feed-item" style="padding: 15px; margin-bottom:12px; ${requiresReview ? 'border-color: rgba(255, 42, 95, 0.25); background: rgba(255, 42, 95, 0.01);' : ''}">
                    <div class="feed-item-header" style="padding:0 0 10px;">
                        <div>
                            <h4 style="font-size:12px;">@${post.username} (${post.source})</h4>
                            <p style="font-size:10px; color:var(--text-muted);">Post ID: ${post.post_id} • Ingested: ${formatDate(post.created_at)}</p>
                        </div>
                        <span class="badge ${post.status}">${post.status.replace(/_/g, ' ')}</span>
                    </div>
                    
                    <div style="font-size:12px; margin-bottom:12px;">${post.content}</div>
                    
                    <div class="feed-item-routing">
                        <div class="route-info">
                            <span class="route-label">Verification Score:</span>
                            <span class="route-value ${post.confidence_score >= 0.95 ? 'green' : 'red'}">${scorePercent}</span>
                        </div>
                        ${post.matched_snippet ? `
                            <div class="route-info" style="flex-direction: column; gap: 4px;">
                                <span class="route-label">Closest Fact Snippet Match:</span>
                                <span class="route-value" style="font-weight:normal; font-style:italic; color:var(--text-secondary); background:rgba(255,255,255,0.02); padding:6px; border-radius:6px; border:1px solid var(--border-glass)">
                                    "${post.matched_snippet}"
                                </span>
                            </div>
                        ` : ''}
                    </div>

                    ${requiresReview ? `
                        <div class="feed-item-actions">
                            <button class="btn btn-danger btn-block" style="padding:6px; font-size:11px;" onclick="adminRejectPost('${post.post_id}')">
                                Reject
                            </button>
                            <button class="btn btn-glow btn-block" style="padding:6px; font-size:11px;" onclick="adminApprovePost('${post.post_id}')">
                                Approve Override
                            </button>
                        </div>
                    ` : ''}
                </div>
            `;
        }).join('');
        
    } catch (e) {
        list.innerHTML = '<div class="empty-state">Error loading pipeline logs.</div>';
    }
}

// Hook tab clicks inside admin panel
document.getElementById('tab-all').onclick = (e) => {
    activeAdminTab = 'all';
    document.getElementById('tab-all').classList.add('active');
    document.getElementById('tab-review').classList.remove('active');
    loadAdminQueue();
};

document.getElementById('tab-review').onclick = (e) => {
    activeAdminTab = 'review';
    document.getElementById('tab-review').classList.add('active');
    document.getElementById('tab-all').classList.remove('active');
    loadAdminQueue();
};

// Admin Approve Action
async function adminApprovePost(postId) {
    try {
        const response = await fetch(`/posts/${postId}/approve`, { method: 'POST', headers: getHeaders() });
        if (response.ok) {
            await loadAdminQueue();
        } else {
            const err = await response.json();
            alert("Approve failed: " + (err.detail || response.statusText));
        }
    } catch {
        alert("Network error.");
    }
}

// Admin Reject Action
async function adminRejectPost(postId) {
    if (!confirm("Reject and discard this story?")) return;
    try {
        const response = await fetch(`/posts/${postId}/reject`, { method: 'POST', headers: getHeaders() });
        if (response.ok) {
            await loadAdminQueue();
        } else {
            const err = await response.json();
            alert("Reject failed: " + (err.detail || response.statusText));
        }
    } catch {
        alert("Network error.");
    }
}


// --- 8. OVERLAY: COMMENTS SYSTEM ---
async function openCommentsDrawer(postId) {
    activeCommentsPostId = postId;
    const drawer = document.getElementById('comments-modal');
    const container = document.getElementById('comments-list-container');
    
    drawer.classList.add('active');
    container.innerHTML = '<div class="empty-state">Loading comments...</div>';
    
    try {
        const response = await fetch(`/posts/${postId}/comments`, { headers: getHeaders() });
        if (response.ok) {
            const comments = await response.json();
            if (comments.length === 0) {
                container.innerHTML = '<div class="empty-state">No comments yet. Be the first to express opinion!</div>';
                return;
            }
            container.innerHTML = comments.map(c => {
                const avatar = getAvatarUrl(c.avatar_index, c.username);
                return `
                    <div class="comment-item">
                        <img src="${avatar}" alt="Avatar" class="avatar-sm">
                        <div class="comment-item-content">
                            <h5 onclick="closeCommentsModal(); loadUserProfile('${c.username}')" style="cursor:pointer;">${c.username}</h5>
                            <p>${c.text}</p>
                            <span>${formatDate(c.created_at)}</span>
                        </div>
                    </div>
                `;
            }).join('');
        }
    } catch (e) {
        container.innerHTML = '<div class="empty-state">Failed to load comments list.</div>';
    }
}

function closeCommentsModal() {
    document.getElementById('comments-modal').classList.remove('active');
    activeCommentsPostId = null;
}

document.getElementById('comments-close-btn').addEventListener('click', closeCommentsModal);

// Comment submit Form action
document.getElementById('comments-submit-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    if (!activeCommentsPostId) return;
    
    const input = document.getElementById('comment-text-input');
    const text = input.value.trim();
    if (!text) return;
    
    try {
        const response = await fetch(`/posts/${activeCommentsPostId}/comments`, {
            method: 'POST',
            headers: getHeaders(),
            body: JSON.stringify({ text: text })
        });
        if (response.ok) {
            input.value = '';
            await openCommentsDrawer(activeCommentsPostId);
            // Refresh reels count if active
            if (activeView === 'reels') loadReelsSwiper();
        }
    } catch (e) {
        console.error(e);
    }
});


// --- 9. OVERLAY: POST DETAIL MODAL ---
async function openPostDetailModal(postId) {
    const modal = document.getElementById('post-detail-modal');
    const card = document.getElementById('post-detail-card-content');
    
    modal.classList.add('active');
    card.innerHTML = '<div class="empty-state">Loading post details...</div>';
    
    try {
        const response = await fetch(`/posts/${postId}`, { headers: getHeaders() });
        if (!response.ok) throw new Error();
        const post = await response.json();
        
        const userAvatar = getAvatarUrl(post.user_id ? ((post.user_id % 8) + 1) : 1, post.username);
        const scorePercent = (post.confidence_score * 100).toFixed(0) + '%';
        
        card.innerHTML = `
            <div class="feed-item" style="border: none;">
                <div class="feed-item-header">
                    <div class="feed-item-user-info" onclick="closePostDetailModal(); loadUserProfile('${post.username}')">
                        <img src="${userAvatar}" alt="Avatar" class="avatar-sm">
                        <div>
                            <h4>${post.username} <span class="verified-checkmark">✓</span></h4>
                            <p>${post.source} • ${formatDate(post.created_at)}</p>
                        </div>
                    </div>
                    <button class="phone-close-btn" onclick="closePostDetailModal()">&times;</button>
                </div>
                
                ${post.image_path ? `
                <div class="feed-item-media">
                    <img src="/posts/${post.post_id}/image" alt="News Image Card">
                    <div class="media-play-overlay" onclick="closePostDetailModal(); openReelPlayer('${post.post_id}', '${post.username}', '${post.content.replace(/'/g, "\\'")}', ${post.likes_count})">
                        <div class="play-circle">
                            <svg width="24" height="24" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5V19L19 12L8 5Z"/></svg>
                        </div>
                    </div>
                </div>
                ` : `
                <div class="feed-item-media text-card-media" style="background: linear-gradient(135deg, #181528 0%, #110d21 100%); display: flex; flex-direction: column; justify-content: center; align-items: center; padding: 25px; text-align: center; border-radius: 8px; border: 1px solid var(--border-glass); min-height: 120px;">
                    <span class="text-card-source" style="color: var(--accent-cyan); font-size: 11px; text-transform: uppercase; font-weight: 700; margin-bottom: 8px; letter-spacing: 2px;">📢 ${post.source} ALERT</span>
                    <p class="text-card-content" style="color: #fff; font-size: 15px; font-weight: 600; line-height: 1.4; font-family: var(--font-heading);">${post.content}</p>
                </div>
                `}
                
                <div class="feed-item-actions-bar">
                    <button class="action-icon-btn" onclick="toggleLike('${post.post_id}', this)">
                        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M19 14c1.49-1.46 3-3.21 3-5.5A5.5 5.5 0 0 0 16.5 3c-1.76 0-3 .5-4.5 2-1.5-1.5-2.74-2-4.5-2A5.5 5.5 0 0 0 2 8.5c0 2.3 1.5 4.05 3 5.5l7 7Z"/></svg>
                    </button>
                    <button class="action-icon-btn" onclick="closePostDetailModal(); openCommentsDrawer('${post.post_id}')">
                        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"/></svg>
                    </button>
                    
                    ${post.accuracy_percentage !== null ? `
                    <button class="action-icon-btn fact-check-badge" style="color: ${post.accuracy_percentage >= 80 ? '#00f0ff' : (post.accuracy_percentage >= 50 ? '#ffb700' : '#ff4747')}; border-color: ${post.accuracy_percentage >= 80 ? '#00f0ff' : (post.accuracy_percentage >= 50 ? '#ffb700' : '#ff4747')}40; background: ${post.accuracy_percentage >= 80 ? '#00f0ff' : (post.accuracy_percentage >= 50 ? '#ffb700' : '#ff4747')}10; font-weight: 700;">
                        🛡️ AI Checked: ${post.accuracy_percentage}% Accuracy
                    </button>
                    ` : `
                    <button class="action-icon-btn fact-check-badge">
                        🛡️ Match: ${scorePercent}
                    </button>
                    `}
                </div>
                
                <div class="feed-item-stats" style="margin-bottom:12px;">
                    <span id="like-count-${post.post_id}">${post.likes_count}</span> likes
                </div>
                
                <div class="feed-item-caption" style="padding-bottom:10px;">
                    <strong>${post.username}</strong> ${post.content}
                </div>

                ${post.fact_check_report ? `
                <div class="ai-report-box" style="margin-top: 15px; padding: 15px; background: rgba(255,255,255,0.02); border-radius: 8px; border: 1px solid var(--border-glass); max-height: 250px; overflow-y: auto; text-align: left;">
                    <h4 style="color: var(--accent-cyan); font-size: 11px; font-weight: 700; text-transform: uppercase; margin-bottom: 8px; border-bottom: 1px solid var(--border-glass); padding-bottom: 4px; letter-spacing: 1px;">📋 Gemini Fact Check Report</h4>
                    <div style="font-size: 12px; line-height: 1.6; color: var(--text-secondary);">
                        ${formatMarkdown(post.fact_check_report)}
                    </div>
                </div>
                ` : ''}
            </div>
        `;
    } catch (e) {
        card.innerHTML = '<div class="empty-state">Failed to load detail info.</div>';
    }
}

function closePostDetailModal() {
    document.getElementById('post-detail-modal').classList.remove('active');
}

// Close detail modal when clicking outside content area
document.getElementById('post-detail-modal').addEventListener('click', (e) => {
    if (e.target === document.getElementById('post-detail-modal')) closePostDetailModal();
});


// --- 10. OVERLAY: EDIT PROFILE MODAL ---
function openSettingsModal() {
    const modal = document.getElementById('settings-modal');
    modal.classList.add('active');
    
    // Autofill
    document.getElementById('settings-display-name').value = currentUser.display_name || '';
    document.getElementById('settings-bio').value = currentUser.bio || '';
    selectedAvatarIndex = currentUser.avatar_index;
    
    // Reset avatar selectors
    document.querySelectorAll('.avatar-option').forEach(img => {
        const idx = parseInt(img.getAttribute('data-index'));
        if (idx === selectedAvatarIndex) {
            img.classList.add('selected');
        } else {
            img.classList.remove('selected');
        }
    });
}

function closeSettingsModal() {
    document.getElementById('settings-modal').classList.remove('active');
}

document.getElementById('settings-close-btn').addEventListener('click', closeSettingsModal);

// Avatar option clicks selector
document.querySelectorAll('.avatar-option').forEach(img => {
    img.addEventListener('click', () => {
        document.querySelectorAll('.avatar-option').forEach(a => a.classList.remove('selected'));
        img.classList.add('selected');
        selectedAvatarIndex = parseInt(img.getAttribute('data-index'));
    });
});

// Update profile form submit
document.getElementById('form-update-profile').addEventListener('submit', async (e) => {
    e.preventDefault();
    const displayName = document.getElementById('settings-display-name').value.trim();
    const bio = document.getElementById('settings-bio').value.trim();
    
    try {
        const response = await fetch('/auth/update', {
            method: 'POST',
            headers: getHeaders(),
            body: JSON.stringify({
                display_name: displayName,
                bio: bio,
                avatar_index: selectedAvatarIndex
            })
        });
        if (response.ok) {
            currentUser = await response.json();
            setupUserFooter();
            closeSettingsModal();
            loadUserProfile(currentUser.username);
        } else {
            alert("Failed to update profile.");
        }
    } catch {
        alert("Network error.");
    }
});


// --- 11. OVERLAY: MOUNTED REELS MODAL ---
const videoModal = document.getElementById('video-modal');
const modalClose = document.getElementById('modal-close');
const reelPlayer = document.getElementById('reel-player');
const reelLikes = document.getElementById('reel-likes');
const reelAuthor = document.getElementById('reel-author');
const reelCaption = document.getElementById('reel-caption');

function openReelPlayer(postId, username, caption, likes) {
    reelPlayer.src = `/posts/${postId}/video`;
    reelLikes.textContent = likes;
    reelAuthor.textContent = '@' + username;
    reelCaption.textContent = caption;
    
    videoModal.classList.add('active');
    reelPlayer.play().catch(e => console.log(e));
    
    // Dynamic reel modal like hook
    document.getElementById('reel-likes-action-btn').onclick = async () => {
        const res = await fetch(`/posts/${postId}/like?action=like`, {
            method: 'POST',
            headers: getHeaders()
        });
        if (res.ok) {
            const data = await res.json();
            reelLikes.textContent = data.likes_count;
            // Update cache/feed states
            if (activeView === 'home') loadHomeFeed();
        }
    };
    
    document.getElementById('reel-comments-action-btn').onclick = () => {
        closeReelPlayer();
        openCommentsDrawer(postId);
    };
}

function closeReelPlayer() {
    videoModal.classList.remove('active');
    reelPlayer.pause();
    reelPlayer.src = '';
}

modalClose.addEventListener('click', closeReelPlayer);
videoModal.addEventListener('click', (e) => {
    if (e.target === videoModal) closeReelPlayer();
});


// --- 12. MOCK DATA SCRAPE SANDBOX FORM ACTION ---
document.getElementById('form-ingest').addEventListener('submit', async (e) => {
    e.preventDefault();
    
    const payload = {
        source: document.getElementById('post-source').value,
        post_id: document.getElementById('post-id').value.trim(),
        username: document.getElementById('post-username').value.trim(),
        content: document.getElementById('post-content').value.trim(),
        timestamp: new Date().toISOString(),
        metadata: {
            likes: parseInt(document.getElementById('post-likes').value) || 0,
            retweets: parseInt(document.getElementById('post-retweets').value) || 0
        }
    };
    
    try {
        const response = await fetch('/ingest', {
            method: 'POST',
            headers: getHeaders(),
            body: JSON.stringify(payload)
        });
        
        if (response.ok) {
            document.getElementById('form-ingest').reset();
            document.getElementById('post-id').value = 'post_' + Math.floor(Math.random() * 9000 + 1000);
            alert("Social post ingested into pipeline! Click 'Admin Panel' to watch processing status.");
            navigateTo('admin');
        } else {
            const err = await response.json();
            alert("Error: " + (err.detail || response.statusText));
        }
    } catch {
        alert("Network error.");
    }
});


// --- 13. REGISTER KNOWLEDGE FACT SHEETS ---
document.getElementById('form-kb').addEventListener('submit', async (e) => {
    e.preventDefault();
    const title = document.getElementById('kb-title').value.trim();
    const content = document.getElementById('kb-content').value.trim();
    
    try {
        const response = await fetch('/trusted-docs', {
            method: 'POST',
            headers: getHeaders(),
            body: JSON.stringify({ title, content })
        });
        
        if (response.ok) {
            document.getElementById('form-kb').reset();
            alert("Reference document successfully loaded for fact checking similarity checking!");
            loadAdminPanel();
        } else {
            const err = await response.json();
            alert("Error: " + (err.detail || response.statusText));
        }
    } catch {
        alert("Network error.");
    }
});


// --- 14. RESET PIPELINE STATE ---
document.getElementById('btn-reset').addEventListener('click', async () => {
    if (!confirm("WARNING: This will delete ALL posts, users, saved bookmarks, comments, and local generated images/videos. Continue?")) return;
    try {
        const response = await fetch('/reset', { method: 'POST', headers: getHeaders() });
        if (response.ok) {
            alert("Platform database and folders fully wiped. Logging out.");
            setSessionToken(null);
            showAuthModal(true);
        }
    } catch {
        alert("Reset failed.");
    }
});


// --- 15. PRESET SANDBOX TEMPLATES ---
document.getElementById('tpl-match').addEventListener('click', () => {
    document.getElementById('post-source').value = "X";
    document.getElementById('post-id').value = 'post_' + Math.floor(Math.random() * 9000 + 1000);
    document.getElementById('post-username').value = "nasa_reporter";
    document.getElementById('post-content').value = "NASA Artemis astronauts will land on the lunar south pole next year to conduct geological surveys.";
    document.getElementById('post-likes').value = 920;
    document.getElementById('post-retweets').value = 45;
});

document.getElementById('tpl-unverified').addEventListener('click', () => {
    document.getElementById('post-source').value = "Instagram";
    document.getElementById('post-id').value = 'post_' + Math.floor(Math.random() * 9000 + 1000);
    document.getElementById('post-username').value = "cosmic_weekly";
    document.getElementById('post-content').value = "Leak reveals astronauts are quitting NASA Artemis mission due to alien sightings.";
    document.getElementById('post-likes').value = 450;
    document.getElementById('post-retweets').value = 0;
});


// --- 16. AUTHENTICATION FORMS TOGGLES & SUBMITS ---
document.getElementById('toggle-to-signup').addEventListener('click', () => {
    document.getElementById('form-login').classList.add('hidden');
    document.getElementById('form-signup').classList.remove('hidden');
});

document.getElementById('toggle-to-login').addEventListener('click', () => {
    document.getElementById('form-signup').classList.add('hidden');
    document.getElementById('form-login').classList.remove('hidden');
});

// Google Auth modal toggle handlers
const googleModal = document.getElementById('google-modal');
const googleLoginButton = document.getElementById('btn-google-login');
const googleSignupButton = document.getElementById('btn-google-signup');
const googleCancelButton = document.getElementById('btn-google-cancel');
const googleSignInForm = document.getElementById('form-google-signin');

function openGoogleModal(e) {
    e.preventDefault();
    if (googleModal) {
        googleModal.classList.add('active');
    }
}

if (googleLoginButton) googleLoginButton.addEventListener('click', openGoogleModal);
if (googleSignupButton) googleSignupButton.addEventListener('click', openGoogleModal);
if (googleCancelButton) {
    googleCancelButton.addEventListener('click', (e) => {
        e.preventDefault();
        googleModal?.classList.remove('active');
        googleSignInForm?.reset();
    });
}

if (googleSignInForm) {
    googleSignInForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const emailInput = document.getElementById('google-email');
        const displayNameInput = document.getElementById('google-name');
        const email = emailInput?.value.trim() || '';
        const displayName = displayNameInput?.value.trim() || '';

        if (!email.toLowerCase().endsWith('@gmail.com')) {
            alert('Google Sign-In is restricted to valid @gmail.com accounts only.');
            return;
        }

        try {
            const response = await apiFetch('/auth/google', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ email: email.toLowerCase(), display_name: displayName })
            });

            if (!response.ok) {
                const err = await response.json().catch(() => ({}));
                alert('Google Sign-In failed: ' + (err.detail || 'Authentication error'));
                return;
            }

            const data = await response.json();
            setSessionToken(data.token, data.user);
            googleSignInForm.reset();
            googleModal?.classList.remove('active');
            await checkAuth();
        } catch (err) {
            console.error('Google Sign-In request failed:', err);
            alert('Network error. Please try again.');
        }
    });
}

// Login Form Submit Action
document.getElementById('form-login').addEventListener('submit', async (e) => {
    e.preventDefault();
    const username = document.getElementById('login-username').value.trim();
    const password = document.getElementById('login-password').value;
    
    try {
        const response = await apiFetch('/auth/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username_or_email: username, password })
        });
        if (response.ok) {
            const data = await response.json();
            setSessionToken(data.token, data.user);
            document.getElementById('form-login').reset();
            await checkAuth();
            ensureKeyPair(); // Generate E2EE key pair and publish public key
        } else {
            const err = await response.json();
            alert("Login failed: " + (err.detail || "Invalid credentials"));
        }
    } catch {
        alert("Network error.");
    }
});

// Signup Form Submit Action
document.getElementById('form-signup').addEventListener('submit', async (e) => {
    e.preventDefault();
    const username = document.getElementById('signup-username').value.trim();
    const email = document.getElementById('signup-email').value.trim();
    const password = document.getElementById('signup-password').value;
    const displayName = document.getElementById('signup-name').value.trim();
    
    if (!email.toLowerCase().endsWith("@gmail.com")) {
        alert("Registration is restricted to valid @gmail.com accounts only.");
        return;
    }
    
    try {
        const response = await apiFetch('/auth/signup', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, email, password, display_name: displayName })
        });
        if (response.ok) {
            const data = await response.json();
            setSessionToken(data.token, data.user);
            document.getElementById('form-signup').reset();
            await checkAuth();
        } else {
            const err = await response.json();
            alert("Signup failed: " + (err.detail || "Invalid values"));
        }
    } catch {
        alert("Network error.");
    }
});

// Logout Action
document.getElementById('btn-logout').addEventListener('click', (e) => {
    e.preventDefault();
    if (!confirm("Are you sure you want to log out?")) return;
    setSessionToken(null);
    currentUser = null;
    setupUserFooter();
    showAuthModal(true);
});


// --- 17. OVERLAY: FORGOT PASSWORD MODAL ---
const forgotPwdModal = document.getElementById('forgot-pwd-modal');
const formForgotRequest = document.getElementById('form-forgot-request');
const formForgotReset = document.getElementById('form-forgot-reset');
const forgotSubtitle = document.getElementById('forgot-pwd-subtitle');

// Show modal
document.getElementById('btn-forgot-pwd').addEventListener('click', (e) => {
    e.preventDefault();
    forgotPwdModal.classList.add('active');
    formForgotRequest.classList.remove('hidden');
    formForgotReset.classList.add('hidden');
    forgotSubtitle.textContent = "Enter your email to receive a password reset PIN";
});

// Hide modal on Cancel clicks
document.querySelectorAll('.btn-forgot-cancel').forEach(btn => {
    btn.addEventListener('click', (e) => {
        e.preventDefault();
        forgotPwdModal.classList.remove('active');
        formForgotRequest.reset();
        formForgotReset.reset();
    });
});

// Step 1: Submit Reset Request (Generate PIN)
formForgotRequest.addEventListener('submit', async (e) => {
    e.preventDefault();
    const email = document.getElementById('forgot-email').value.trim();
    if (!email) return;

    try {
        const response = await apiFetch('/auth/forgot-password', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email: email })
        });

        if (response.ok) {
            const data = await response.json();
            const resetCode = data.reset_code || data.resetCode || '';
            // Autofill email for confirmation step
            document.getElementById('reset-email').value = email;
            
            // Toggle forms
            formForgotRequest.classList.add('hidden');
            formForgotReset.classList.remove('hidden');
            if (resetCode) {
                forgotSubtitle.textContent = `Your reset PIN is ${resetCode}. Enter it below to continue.`;
            } else {
                forgotSubtitle.textContent = "A reset PIN has been generated. Enter it below to continue.";
            }
            
            // Inform the user the PIN is ready
            alert(`Reset PIN successfully generated!${resetCode ? `\n\nYour PIN: ${resetCode}` : ''}`);
        } else {
            const err = await response.json();
            alert("Error: " + (err.detail || "Email address not found."));
        }
    } catch {
        alert("Network error.");
    }
});

// Step 2: Submit Reset Password Form
formForgotReset.addEventListener('submit', async (e) => {
    e.preventDefault();
    const email = document.getElementById('reset-email').value.trim();
    const code = document.getElementById('reset-pin').value.trim();
    const newPassword = document.getElementById('reset-new-password').value;

    try {
        const response = await apiFetch('/auth/reset-password', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                email: email,
                code: code,
                new_password: newPassword
            })
        });

        if (response.ok) {
            alert("Password updated successfully! You can now log in with your new credentials.");
            forgotPwdModal.classList.remove('active');
            formForgotRequest.reset();
            formForgotReset.reset();
        } else {
            const err = await response.json();
            alert("Reset failed: " + (err.detail || "Invalid or expired PIN."));
        }
    } catch {
        alert("Network error.");
    }
});


// --- INITIAL STARTUP HANDLER ---
window.addEventListener('DOMContentLoaded', () => {
    // Generate initial random Post ID for preset testing
    document.getElementById('post-id').value = 'post_' + Math.floor(Math.random() * 9000 + 1000);
    
    // Bootstrap Session
    checkAuth();
    
    // Status polling loop: Refresh admin queues & feeds every 4 seconds in the background
    setInterval(() => {
        if (activeView === 'admin') loadAdminQueue();
        if (activeView === 'home') loadHomeFeed();
    }, 4000);
});
