// Krax Content Script for Grok.com
// Injects prompts and extracts responses using Grok-oriented selectors.

console.log("%c KRAX CONTENT SCRIPT LOADED ", "background: #222; color: #ffeb3b; font-size: 20px");

window.kraxDebugLog = "";

chrome.runtime.onMessage.addListener((request) => {
    if (request.type === "EXECUTE_JOB") {
        runJob(request.job).catch((error) => {
            sendError(request.job.id, error.message);
        });
    }
});

async function runJob(job) {
    console.log("Krax Executing Job:", job.id);
    document.body.style.border = "10px solid red";
    window.kraxDebugLog = "Started job. ";

    const messageCountBefore = countGrokMessages();
    
    if (job.attachments && job.attachments.length > 0) {
        await injectAttachments(job.attachments);
        await sleep(1000); // Give frontend time to process blobs visually
    }

    await injectAndSendPrompt(job.prompt);
    await waitForResponseCompletion(messageCountBefore);
    const responseText = scrapeNewestResponse(messageCountBefore);

    document.body.style.border = "10px solid green";
    chrome.runtime.sendMessage({
        type: "JOB_COMPLETE",
        data: {
            id: job.id,
            response: responseText,
            debug: window.kraxDebugLog || "Success",
        },
    });
}

function findPromptTextarea() {
    let area = document.querySelector('textarea[data-testid="prompt-textarea"]');
    if (area) return area;

    area = document.querySelector('div[contenteditable="true"].ProseMirror');
    if (area) return area;

    area = document.querySelector('div[contenteditable="true"]');
    if (area) return area;

    area = document.querySelector("textarea");
    if (area) return area;

    area = document.querySelector('[role="textbox"]');
    if (area) return area;

    const editables = document.querySelectorAll('div[contenteditable="true"]');
    if (editables.length > 0) {
        return editables[editables.length - 1];
    }
    return null;
}

function findSendButton() {
    let button = document.querySelector('[data-testid="send-button"]:not([disabled])');
    if (button) return button;

    button = document.querySelector('button[aria-label="Submit"]:not([disabled])');
    if (button) return button;

    button = document.querySelector('button[type="submit"]:not([disabled])');
    if (button) return button;

    const buttons = Array.from(document.querySelectorAll("button"));
    button = buttons.find((b) => {
        if (b.disabled) return false;
        const text = (b.innerText || "").trim().toLowerCase();
        const label = (b.getAttribute("aria-label") || "").trim().toLowerCase();
        return (
            text === "send" ||
            text.includes("send message") ||
            label.includes("submit") ||
            label.includes("send")
        );
    });
    return button || null;
}

function isVisible(el) {
    if (!el) return false;
    const style = window.getComputedStyle(el);
    if (style.display === "none" || style.visibility === "hidden" || style.opacity === "0") {
        return false;
    }
    return !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
}

function clickElement(el) {
    if (!el) return false;
    el.focus();
    el.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, cancelable: true }));
    el.dispatchEvent(new MouseEvent("mouseup", { bubbles: true, cancelable: true }));
    el.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
    return true;
}

function setContentEditableText(editor, promptText) {
    editor.focus();

    const selection = window.getSelection();
    const range = document.createRange();
    range.selectNodeContents(editor);
    range.collapse(true);
    selection.removeAllRanges();
    selection.addRange(range);

    // ProseMirror often expects real editing operations rather than raw innerText assignment.
    let inserted = false;
    try {
        inserted = document.execCommand("insertText", false, promptText);
    } catch (_) {
        inserted = false;
    }

    if (!inserted) {
        const paragraph = editor.querySelector("p") || editor;
        paragraph.textContent = promptText;
    }
}

async function injectAndSendPrompt(promptText) {
    let textarea = findPromptTextarea();

    if (!textarea) {
        for (let i = 0; i < 20; i++) {
            await sleep(500);
            textarea = findPromptTextarea();
            if (textarea) break;
        }
    }

    if (!textarea) {
        throw new Error("Unable to locate Grok prompt textarea.");
    }

    textarea.focus();
    if (textarea.tagName === "TEXTAREA" || textarea.tagName === "INPUT") {
        textarea.value = promptText;
    } else {
        setContentEditableText(textarea, promptText);
    }

    textarea.dispatchEvent(new Event("input", { bubbles: true }));
    textarea.dispatchEvent(new Event("change", { bubbles: true }));
    textarea.dispatchEvent(new KeyboardEvent("keyup", { key: " ", bubbles: true }));
    await sleep(500);

    for (let i = 0; i < 15; i++) {
        const sendButton = findSendButton();
        if (sendButton && isVisible(sendButton)) {
            clickElement(sendButton);
            window.kraxDebugLog += "Sent via button. ";
            return;
        }
        await sleep(150);
    }

    textarea.dispatchEvent(
        new KeyboardEvent("keydown", {
            key: "Enter",
            code: "Enter",
            keyCode: 13,
            which: 13,
            bubbles: true,
        }),
    );
    textarea.dispatchEvent(
        new KeyboardEvent("keyup", {
            key: "Enter",
            code: "Enter",
            keyCode: 13,
            which: 13,
            bubbles: true,
        }),
    );
    window.kraxDebugLog += "Sent via Enter key fallback. ";
}

async function injectAttachments(attachments) {
    const fileInput = document.querySelector('input[type="file"]');
    if (!fileInput) {
        window.kraxDebugLog += "No file input found for attachments. ";
        return;
    }

    const dt = new DataTransfer();
    for (const att of attachments) {
        const file = new File([att.content], att.filename, { type: "text/plain" });
        dt.items.add(file);
    }

    fileInput.files = dt.files;
    fileInput.dispatchEvent(new Event('change', { bubbles: true }));
    window.kraxDebugLog += `Injected ${attachments.length} attachments. `;
}

function responseCandidates() {
    const selectors = [
        ".prose",
        ".markdown",
        "article",
        "[data-message-author-role='assistant']",
        "[data-testid*='assistant']",
        "[class*='message']",
    ];

    const nodes = Array.from(document.querySelectorAll(selectors.join(",")));
    return nodes.filter((node) => {
        if (!node) return false;
        if (node.closest('[contenteditable="true"]')) return false;
        const text = (node.innerText || "").trim();
        if (!text) return false;
        if (text === "What's on your mind?") return false;
        return true;
    });
}

function countGrokMessages() {
    return responseCandidates().length;
}

function isStillGenerating() {
    const buttons = Array.from(document.querySelectorAll("button"));
    const stopBtn = buttons.find((b) => {
        const text = (b.innerText || "").toLowerCase();
        return text.includes("stop") || text.includes("cancel") || text.includes("generating");
    });
    if (stopBtn) return true;

    return !!document.querySelector(".streaming, .generating, [data-state='streaming']");
}

function waitForResponseCompletion(initialMessageCount) {
    return new Promise((resolve, reject) => {
        let lastMutationTime = Date.now();
        let sawNewMessage = false;
        const MAX_TIMEOUT = 120000;

        const observer = new MutationObserver(() => {
            lastMutationTime = Date.now();
            if (countGrokMessages() > initialMessageCount) {
                sawNewMessage = true;
            }
        });

        const settleInterval = setInterval(() => {
            const timeSinceLastMutation = Date.now() - lastMutationTime;
            if (sawNewMessage && !isStillGenerating() && timeSinceLastMutation > 2500) {
                clearInterval(settleInterval);
                clearTimeout(timeoutId);
                observer.disconnect();
                window.kraxDebugLog += "Generation finished (DOM settled). ";
                resolve(true);
            }
        }, 800);

        const timeoutId = setTimeout(() => {
            clearInterval(settleInterval);
            observer.disconnect();
            reject(new Error(`Timeout waiting for Grok response completion after ${MAX_TIMEOUT}ms.`));
        }, MAX_TIMEOUT);

        observer.observe(document.body, { childList: true, subtree: true, characterData: true });
    });
}

function scrapeNewestResponse(initialMessageCount) {
    const msgs = responseCandidates();

    if (msgs.length <= initialMessageCount) {
        throw new Error("No new Grok response found in DOM.");
    }

    const newestMsg = msgs[msgs.length - 1];
    const text = newestMsg.innerText;
    window.kraxDebugLog += `Scraped response (${text.length} chars). `;
    return text;
}

function sendError(jobId, errorMsg) {
    console.error("Krax content script error:", errorMsg);
    document.body.style.border = "10px solid orange";

    chrome.runtime.sendMessage({
        type: "JOB_FAIL",
        data: {
            id: jobId,
            error: errorMsg,
        },
    });
}

function sleep(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
}
