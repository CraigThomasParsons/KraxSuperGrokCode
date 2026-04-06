// background.js for Krax Automation
// Defines the background service worker that polls the local Krax Server
// and automatically refreshes Grok session cookies.

// The local Krax server will be running on port 3001 to avoid Auralis conflicts
const SERVER_URL = "http://localhost:3001";
let processingJobId = null;
let activeTabId = null;
const POLL_ALARM = "kraxPoll";
const POLL_MINUTES = 0.1; // 6 seconds

// Cookie refresh runs on a separate alarm — every 1 minute it extracts
// the sso/sso-rw cookies from grok.com and POSTs them to the Krax server
// so the API client always has fresh credentials without manual intervention.
const COOKIE_REFRESH_ALARM = "grokCookieRefresh";
const COOKIE_REFRESH_MINUTES = 1;

// ─────────────────────────────────────────────────────
// Cookie Extraction — keeps config.yaml fresh overnight
// ─────────────────────────────────────────────────────

async function extractGrokCookies() {
    try {
        // Search across all domains Grok might set auth cookies on.
        // The sso and sso-rw cookies are set by x.com's auth system
        // since Grok shares the X/Twitter SSO infrastructure.
        const cookieDomains = ["grok.com", ".grok.com", "x.com", ".x.com", "x.ai", ".x.ai"];
        let allCookies = [];

        // Domain-based lookup captures cookies regardless of path.
        for (const domain of cookieDomains) {
            const cookies = await chrome.cookies.getAll({ domain });
            if (cookies.length > 0) {
                allCookies = allCookies.concat(cookies);
            }
        }

        // URL-based lookup as a fallback — sometimes domain-based misses
        // cookies that were set with a specific path attribute.
        const cookieUrls = ["https://grok.com/", "https://x.com/", "https://x.ai/"];
        for (const url of cookieUrls) {
            const cookies = await chrome.cookies.getAll({ url });
            if (cookies.length > 0) {
                allCookies = allCookies.concat(cookies);
            }
        }

        // Deduplicate by name+domain to avoid counting the same cookie twice
        // from overlapping domain/URL results.
        const seenCookieKeys = new Set();
        allCookies = allCookies.filter(cookieEntry => {
            const deduplicationKey = `${cookieEntry.name}@${cookieEntry.domain}`;
            if (seenCookieKeys.has(deduplicationKey)) return false;
            seenCookieKeys.add(deduplicationKey);
            return true;
        });

        if (allCookies.length === 0) {
            console.warn("[Krax Cookie] No cookies found on Grok/X domains. Are you logged in?");
            return;
        }

        // Extract the specific SSO cookies that the Grok API requires.
        // These are set by x.com's auth infrastructure and shared with grok.com.
        const ssoCookie = allCookies.find(cookieEntry => cookieEntry.name === "sso");
        const ssoRwCookie = allCookies.find(cookieEntry => cookieEntry.name === "sso-rw");

        // Build the raw Cookie header string in the format grok_api_client expects.
        // The API client sends this as-is in the Cookie: header of every request.
        const cookieParts = [];
        if (ssoCookie && ssoCookie.value) {
            cookieParts.push(`sso=${ssoCookie.value}`);
        }
        if (ssoRwCookie && ssoRwCookie.value) {
            cookieParts.push(`sso-rw=${ssoRwCookie.value}`);
        }

        if (cookieParts.length === 0) {
            // No SSO cookies found — try a broader search for any auth-looking
            // cookies in case Grok changes their cookie naming convention.
            const authCookie = allCookies.find(cookieEntry =>
                cookieEntry.name.includes("sso") ||
                cookieEntry.name.includes("session") ||
                cookieEntry.name.includes("auth")
            );
            if (authCookie) {
                console.log(`[Krax Cookie] Fallback: found "${authCookie.name}" on ${authCookie.domain}`);
                cookieParts.push(`${authCookie.name}=${authCookie.value}`);
            } else {
                console.warn("[Krax Cookie] No SSO or auth cookies found among", allCookies.length, "cookies");
                console.warn("[Krax Cookie] Available cookies:", allCookies.map(c => `${c.name}@${c.domain}`));
                return;
            }
        }

        const cookieString = cookieParts.join("; ");

        // Look for a device ID cookie — Grok sometimes uses this for rate limiting.
        const deviceCookie = allCookies.find(cookieEntry =>
            cookieEntry.name.includes("device") || cookieEntry.name === "x-device-id"
        );
        const deviceIdValue = deviceCookie ? deviceCookie.value : "";

        // POST the extracted cookie to the Krax server's config update endpoint.
        // The server writes this to config.yaml so the GrokApiClient picks it up.
        const response = await fetch(`${SERVER_URL}/api/cookie/update`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                cookie_string: cookieString,
                device_id: deviceIdValue
            })
        });

        if (!response.ok) {
            console.error(`[Krax Cookie] Server returned ${response.status} ${response.statusText}`);
            return;
        }

        const responseData = await response.json();
        console.log(`[Krax Cookie] Updated successfully (${cookieString.length} chars):`, responseData.message || "OK");

        // Record the last successful refresh for debugging in chrome://extensions.
        chrome.storage.local.set({
            lastCookieUpdate: new Date().toISOString(),
            lastCookieLength: cookieString.length
        });

    } catch (extractionError) {
        // Don't let cookie extraction failures interfere with job polling —
        // the two systems are independent and should fail independently.
        console.error("[Krax Cookie] Extraction error:", extractionError);
    }
}

// ─────────────────────────────────────────────────────
// Job Polling — existing Auralis/Grok automation logic
// ─────────────────────────────────────────────────────

async function pollForJob() {
    // If we are currently holding a lock for a job, skip polling
    // This ensures we do not overlap requests or overwhelm Grok
    if (processingJobId) {
        return;
    }

    try {
        // Attempt to fetch a new job from the local queue
        const res = await fetch(`${SERVER_URL}/job`);
        const job = await res.json();

        // If a valid job payload was supplied by the server, lock it
        // The lock prevents duplicate polling cycles from seizing it
        if (job && job.id) {
            console.log("Krax found job:", job);
            processingJobId = job.id; 
            processJob(job);
        }
    } catch (e) {
        console.warn("Krax poll failed:", e?.message || e);
    }
}

// MV3 service workers can sleep, so use alarms instead of setInterval polling.
// Two alarms: one for job polling (6s), one for cookie refresh (1min).
chrome.runtime.onInstalled.addListener(() => {
    chrome.alarms.create(POLL_ALARM, { periodInMinutes: POLL_MINUTES });
    chrome.alarms.create(COOKIE_REFRESH_ALARM, { periodInMinutes: COOKIE_REFRESH_MINUTES });
});

chrome.runtime.onStartup.addListener(() => {
    chrome.alarms.create(POLL_ALARM, { periodInMinutes: POLL_MINUTES });
    chrome.alarms.create(COOKIE_REFRESH_ALARM, { periodInMinutes: COOKIE_REFRESH_MINUTES });
});

// Ensure both alarms exist even if the service worker restarts mid-session.
chrome.alarms.get(POLL_ALARM, (existing) => {
    if (!existing) {
        chrome.alarms.create(POLL_ALARM, { periodInMinutes: POLL_MINUTES });
    }
});
chrome.alarms.get(COOKIE_REFRESH_ALARM, (existing) => {
    if (!existing) {
        chrome.alarms.create(COOKIE_REFRESH_ALARM, { periodInMinutes: COOKIE_REFRESH_MINUTES });
    }
});

chrome.alarms.onAlarm.addListener((alarm) => {
    if (alarm.name === POLL_ALARM) {
        pollForJob();
    } else if (alarm.name === COOKIE_REFRESH_ALARM) {
        extractGrokCookies();
    }
});

// Kick one immediate poll + cookie extraction when the worker wakes.
pollForJob();
extractGrokCookies();

// Spawns or focuses a Grok tab to execute the given job
async function processJob(job) {
    const grokUrls = [
        "*://grok.com/*",
        "*://*.grok.com/*",
        "*://x.com/i/grok*",
        "*://*.x.com/i/grok*",
        "*://x.ai/*",
        "*://*.x.ai/*",
    ];

    // Query Chrome for any existing tabs matching the Grok domain
    // We reuse existing tabs to prevent memory bloat over time
    chrome.tabs.query({ url: grokUrls }, (tabs) => {
        if (tabs.length > 0) {
            // If a tab exists, we make it the active focused tab
            const tab = tabs[0];
            activeTabId = tab.id;
            // Force navigation to the exact job URL (the Code Project)
            chrome.tabs.update(tab.id, { active: true, url: job.url }, () => {
                // Wait for the Grok SPA to fully mount after navigation
                // 5 seconds is a safe buffer for standard connections
                setTimeout(() => sendExecuteJob(tab.id, job), 5000);
            });

        } else {
            // If no Grok tab exists, create a fresh one pointing to grok.com
            // Wait 5 seconds allows the heavy initial React hydrate to finish
            chrome.tabs.create({ url: "https://grok.com/" }, (tab) => {
                activeTabId = tab.id;
                setTimeout(() => sendExecuteJob(tab.id, job), 5000);
            });
        }
    });
}

function releaseLocalLock() {
    processingJobId = null;
    activeTabId = null;
}

function isBenignSendMessageWarning(message) {
    if (!message) return false;
    const normalized = String(message).toLowerCase();
    return normalized.includes("message port closed before a response was received");
}

function reportJobFail(job, errorMessage) {
    const payload = {
        id: job.id,
        error: errorMessage,
    };

    return fetch(`${SERVER_URL}/job/fail`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
    }).catch((err) => {
        console.warn("Failed to notify /job/fail:", err?.message || err);
    });
}

function sendExecuteJob(tabId, job) {
    chrome.tabs.sendMessage(
        tabId,
        {
            type: "EXECUTE_JOB",
            job: job,
        },
        () => {
            if (!chrome.runtime.lastError) {
                return;
            }

            if (isBenignSendMessageWarning(chrome.runtime.lastError.message)) {
                console.debug("EXECUTE_JOB delivered (no response expected):", chrome.runtime.lastError.message);
                return;
            }

            console.warn("Initial EXECUTE_JOB send failed:", chrome.runtime.lastError.message);

            // If the content script has not attached yet, retry once shortly after.
            setTimeout(() => {
                chrome.tabs.sendMessage(tabId, {
                    type: "EXECUTE_JOB",
                    job: job,
                }, () => {
                    if (!chrome.runtime.lastError) {
                        return;
                    }

                    if (isBenignSendMessageWarning(chrome.runtime.lastError.message)) {
                        console.debug("EXECUTE_JOB retry delivered (no response expected):", chrome.runtime.lastError.message);
                        return;
                    }

                    const err = chrome.runtime.lastError.message || "content_script_unreachable";
                    console.warn("Retry EXECUTE_JOB send failed:", err);
                    reportJobFail(job, `dispatch_failed: ${err}`).finally(() => {
                        releaseLocalLock();
                    });
                });
            }, 1500);
        },
    );
}

// Listen for messages bubbling up from the content.js DOM scraper
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    const incomingId = request?.data?.id;
    if (!incomingId) {
        return;
    }

    if (!processingJobId) {
        console.warn("Ignoring callback with no active lock:", request.type, incomingId);
        return;
    }

    if (incomingId !== processingJobId) {
        console.warn(
            "Ignoring stale callback:",
            request.type,
            "incoming=",
            incomingId,
            "expected=",
            processingJobId,
        );
        return;
    }

    // When the content script successfully exfiltrates the Grok response
    if (request.type === "JOB_COMPLETE") {
        console.log("Krax Job Complete:", request.data.id);

        // POST the extracted text back to the local Krax server
        // This completes the 'Think -> Yield' cycle locally
        fetch(`${SERVER_URL}/complete`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(request.data)
        }).then((res) => {
            if (!res.ok) {
                throw new Error(`/complete returned ${res.status}`);
            }
            // Only release the process lock after the server acknowledges
            releaseLocalLock();
        }).catch((err) => {
            console.warn("Failed to complete job:", err?.message || err);
            releaseLocalLock();
        });
    }
    // If the content script encounters an unrecoverable DOM error
    else if (request.type === "JOB_FAIL") {
        console.log("Krax Job Failed:", request.data);

        fetch(`${SERVER_URL}/job/fail`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(request.data),
        })
            .catch((err) => {
                console.warn("Failed to notify /job/fail:", err?.message || err);
            })
            .finally(() => {
                // Release the lock so the system can attempt recovery next cycle.
                releaseLocalLock();
            });
    }
});
