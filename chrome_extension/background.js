// background.js for Krax Automation
// Defines the background service worker that polls the local Krax Server.

// The local Krax server will be running on port 3001 to avoid Auralis conflicts
const SERVER_URL = "http://localhost:3001";
let processingJobId = null;
let activeTabId = null;
const POLL_ALARM = "kraxPoll";
const POLL_MINUTES = 0.1; // 6 seconds

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
chrome.runtime.onInstalled.addListener(() => {
    chrome.alarms.create(POLL_ALARM, { periodInMinutes: POLL_MINUTES });
});

chrome.runtime.onStartup.addListener(() => {
    chrome.alarms.create(POLL_ALARM, { periodInMinutes: POLL_MINUTES });
});

chrome.alarms.get(POLL_ALARM, (existing) => {
    if (!existing) {
        chrome.alarms.create(POLL_ALARM, { periodInMinutes: POLL_MINUTES });
    }
});

chrome.alarms.onAlarm.addListener((alarm) => {
    if (alarm.name === POLL_ALARM) {
        pollForJob();
    }
});

// Kick one immediate poll when the worker wakes.
pollForJob();

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
