import React, { useEffect, useMemo, useRef, useState } from "react";
import "./QA_bot_UI.css";

// ✅ No hardcoded base URL (Vite env)
const API = import.meta.env.VITE_BACKEND_URL || "http://127.0.0.1:5000";

const STEPS = {
    PROJECT: "PROJECT",
    SPRINT: "SPRINT",
    STORY: "STORY",
    CONFIRM_GEN: "CONFIRM_GEN",
    CONFIRM_APPROVE: "CONFIRM_APPROVE",

    AFTER_SAVE_OK: "AFTER_SAVE_OK",
    ASK_AUTOMATION: "ASK_AUTOMATION",

    ASK_CODEGEN_YN: "ASK_CODEGEN_YN",
    SELECT_BROWSER: "SELECT_BROWSER",
    ENTER_APP_URL: "ENTER_APP_URL",
    CONFIRM_APP_URL: "CONFIRM_APP_URL",
    CODEGEN_RUNNING: "CODEGEN_RUNNING",

    WAIT_LOCATOR_PASTE: "WAIT_LOCATOR_PASTE",
    LOCATOR_REVIEW: "LOCATOR_REVIEW",
};

function QABotUI() {
    const userName = useMemo(() => "User", []);
    const bootstrappedRef = useRef(false);
    const chatEndRef = useRef(null);

    const [messages, setMessages] = useState([]);
    const [loading, setLoading] = useState(false);
    const [typedText, setTypedText] = useState("");
    const [step, setStep] = useState(STEPS.PROJECT);

    const [selectedProject, setSelectedProject] = useState(null);
    const [selectedSprint, setSelectedSprint] = useState(null);
    const [selectedStory, setSelectedStory] = useState(null);

    const [storyDetails, setStoryDetails] = useState(null);
    const [generatedFeature, setGeneratedFeature] = useState("");

    const [approvedFileName, setApprovedFileName] = useState("");
    const [locatorMapping, setLocatorMapping] = useState("");

    const [codegenBrowser, setCodegenBrowser] = useState("");
    const [codegenUrl, setCodegenUrl] = useState("");

    const newId = () =>
        (typeof crypto !== "undefined" && crypto.randomUUID)
            ? crypto.randomUUID()
            : String(Date.now()) + Math.random().toString(16).slice(2);

    const pushBot = (text) =>
        setMessages((m) => [...m, { id: newId(), role: "bot", type: "text", text }]);

    const pushUser = (text) =>
        setMessages((m) => [...m, { id: newId(), role: "user", type: "text", text }]);

    const pushBotCode = (title, code) =>
        setMessages((m) => [...m, { id: newId(), role: "bot", type: "code", title, code }]);

    const pushBotInfo = (title, content) =>
        setMessages((m) => [...m, { id: newId(), role: "bot", type: "info", title, content }]);

    const pushBotOptions = (title, options, kind) =>
        setMessages((m) => [
            ...m,
            { id: newId(), role: "bot", type: "options", title, options, kind, disabled: false },
        ]);

    const disableOptionsMessage = (msgId) => {
        setMessages((m) => m.map((x) => (x.id === msgId ? { ...x, disabled: true } : x)));
    };

    // ✅ Standard user reply for option selections
    const pushUserSelection = (kind, option) => {
        const chosen = option?.label || option?.value || "";
        let msg = `You have selected: ${chosen}`;
        if (kind === "project") msg = `You have selected Space: ${chosen}`;
        if (kind === "sprint") msg = `You have selected Iteration: ${chosen}`;
        if (kind === "story") msg = `You have selected Story: ${chosen}`;
        if (kind === "select_browser") msg = `You have selected Browser: ${chosen}`;
        pushUser(msg);
    };

    useEffect(() => {
        chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
    }, [messages, loading]);

    const showDefaultWelcome = () => {
        pushBot("Welcome to the Autonomous SDLC Assistance!");
    };

    // ✅ Optional: health check (helps show true backend connectivity)
    const checkBackend = async () => {
        try {
            const res = await fetch(`${API}/health`);
            if (!res.ok) throw new Error("health failed");
            return true;
        } catch {
            return false;
        }
    };

    const resetConversation = async () => {
        setMessages([]);
        setLoading(false);
        setTypedText("");
        setStep(STEPS.PROJECT);

        setSelectedProject(null);
        setSelectedSprint(null);
        setSelectedStory(null);

        setStoryDetails(null);
        setGeneratedFeature("");

        setApprovedFileName("");
        setLocatorMapping("");
        setCodegenBrowser("");
        setCodegenUrl("");

        showDefaultWelcome();
        await loadProjects(true);
    };

    // ✅ Spaces from Jira via backend (/projects)
    const loadProjects = async (silent = false) => {
        setLoading(true);
        try {
            const ok = await checkBackend();
            if (!ok) {
                pushBot("❌ Backend not reachable. Please start FastAPI server and verify /health.");
                return;
            }

            const res = await fetch(`${API}/projects`);
            const data = await res.json();
            const list = data.projects || [];

            if (!silent) pushBot("Select any one Space from below:");

            pushBotOptions(
                "Select any one Space from below:",
                list.map((p) => ({ value: p.key, label: `${p.name} (${p.key})` })),
                "project"
            );
        } catch {
            pushBot("❌ Unable to fetch Spaces (projects). Please check backend /projects endpoint.");
        } finally {
            setLoading(false);
        }
    };

    // ✅ Iterations from Jira via backend (/sprints/{projectKey})
    const loadSprints = async (projectKey) => {
        setLoading(true);
        try {
            const res = await fetch(`${API}/sprints/${projectKey}`);
            const data = await res.json();
            const list = data.sprints || [];

            pushBot("Select any one Iteration from below:");
            pushBotOptions(
                "Available Iterations:",
                list.map((s) => ({ value: String(s.id), label: s.name })),
                "sprint"
            );
        } catch {
            pushBot("❌ Unable to fetch iterations. Please check backend /sprints/{projectKey} endpoint.");
        } finally {
            setLoading(false);
        }
    };

    // ✅ Stories from Jira via backend (/stories/{sprintId})
    const loadStories = async (sprintId, sprintNameFromClick = "") => {
        setLoading(true);
        try {
            const res = await fetch(`${API}/stories/${sprintId}`);
            const data = await res.json();
            const list = data.stories || [];

            const sprintName =
                (sprintNameFromClick && sprintNameFromClick.trim()) ||
                (selectedSprint?.label && selectedSprint.label.trim()) ||
                (selectedSprint?.value && String(selectedSprint.value).trim()) ||
                "Selected Iteration";

            pushBot(`Select any one story from the selected iteration: "${sprintName}".`);

            pushBotOptions(
                "Available Stories:",
                list.map((st) => ({ value: st.key, label: `${st.key} - ${st.summary}` })),
                "story"
            );
        } catch {
            pushBot("❌ Unable to fetch stories. Please check backend /stories/{sprintId} endpoint.");
        } finally {
            setLoading(false);
        }
    };

    const showStoryInfoCard = (data) => {
        const info =
            `Summary:\n${data.summary}\n\n` +
            `Description:\n${data.description || "(no description)"}\n\n` +
            `Story Details:\n` +
            `Space name: ${selectedProject?.label || selectedProject?.value || "-"}\n` +
            `Iteration name: ${selectedSprint?.label || selectedSprint?.value || "-"}\n` +
            `Story key: ${data.key}\n` +
            `Assigned to: ${data.assignee || "-"}`;

        pushBotInfo("User Story Details:", info);
    };

    // ✅ Story details from backend (/search)
    const loadStoryDetails = async (projectKey, sprintId, storyKey) => {
        setLoading(true);
        try {
            const res = await fetch(`${API}/search`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ project: projectKey, sprint: sprintId, key: storyKey }),
            });

            const data = await res.json();
            if (!res.ok) {
                pushBot(`❌ ${data.detail || "Failed to fetch story details."}`);
                return;
            }

            setStoryDetails(data);
            pushBot(`✅ Selected story: "${data.key}"`);
            showStoryInfoCard(data);

            setStep(STEPS.CONFIRM_GEN);
            pushBot(`Do you want me to generate a Feature file in BDD format for the selected user story: "${data.key}"?`);
            pushBotOptions("Choose an option", [
                { value: "YES", label: "Yes" },
                { value: "NO", label: "No" },
            ], "yesno_generate");
        } catch {
            pushBot("❌ Error fetching story details.");
        } finally {
            setLoading(false);
        }
    };

    // NOTE: Feature generation & automation flow stays as-is (requires backend endpoints you already had)
    const generateFeature = async () => {
        pushBot("Next steps (Feature generation) will be wired after Jira selection is stable.");
    };

    const handleOptionClick = async (msgId, kind, option) => {
        if (loading) return;
        disableOptionsMessage(msgId);

        // ✅ consistent user message
        pushUserSelection(kind, option);

        if (kind === "project") {
            setSelectedProject(option);
            setSelectedSprint(null);
            setSelectedStory(null);
            setStoryDetails(null);
            setGeneratedFeature("");
            setStep(STEPS.SPRINT);
            await loadSprints(option.value);
            return;
        }

        if (kind === "sprint") {
            setSelectedSprint(option);
            setSelectedStory(null);
            setStoryDetails(null);
            setGeneratedFeature("");
            setStep(STEPS.STORY);
            await loadStories(option.value, option.label);
            return;
        }

        if (kind === "story") {
            setSelectedStory(option);
            await loadStoryDetails(selectedProject?.value, selectedSprint?.value, option.value);
            return;
        }

        if (kind === "yesno_generate") {
            if (option.value === "YES") return generateFeature();
            pushBot("Thanks. Restarting...");
            await resetConversation();
            return;
        }
    };

    const handleSend = async () => {
        const raw = typedText.trim();
        if (!raw) return;
        setTypedText("");
        pushUser(raw);
        pushBot("For now, please use the option buttons.");
    };

    useEffect(() => {
        if (bootstrappedRef.current) return;
        bootstrappedRef.current = true;

        (async () => {
            showDefaultWelcome();
            await loadProjects(true);
        })();
    }, []);

    const historyItems = useMemo(
        () => [
            { text: "Conversation History (Coming Soon)" },
            { text: "New Chat (Current)" },
        ],
        []
    );

    const isSendEnabled = !loading && typedText.trim().length > 0;

    return (
        <div className="chatgpt-layout">
            <aside className="chatgpt-sidebar">
                <div className="sidebar-top">
                    <div className="sidebar-title-row">
                        <img className="sidebar-img" src="/bot.png" alt="bot" />
                        <div className="sidebar-title-text">Autonomous SDLC Assistance</div>
                    </div>

                    <button className="new-chat-btn" onClick={resetConversation} disabled={loading}>
                        ⟳ Refresh / New chat
                    </button>
                </div>

                <div className="sidebar-list">
                    {historyItems.map((item, idx) => (
                        <button key={idx} className="sidebar-item-btn" type="button" disabled>
                            {item.text}
                        </button>
                    ))}
                </div>

                <div className="sidebar-footer">
                    <div className="user-pill">
                        <span className="avatar-mini">👤</span>
                        <span>{userName}</span>
                    </div>
                </div>
            </aside>

            <main className="chatgpt-main">
                <header className="chatgpt-header">
                    <div className="header-title">Autonomous SDLC Assistance</div>
                    <div className="header-subtitle">Jira User Story → Gherkin Feature Generator</div>
                </header>

                <section className="chatgpt-messages">
                    {messages.map((msg) => (
                        <div key={msg.id} className={`msg-row ${msg.role}`}>
                            <div className="msg-avatar">{msg.role === "bot" ? "🤖" : "👤"}</div>

                            <div className={`msg-bubble ${msg.role}`}>
                                {msg.type === "text" && <div className="msg-text">{msg.text}</div>}

                                {msg.type === "info" && (
                                    <div className="info-box">
                                        <div className="info-title">{msg.title}</div>
                                        <pre className="info-content">{msg.content}</pre>
                                    </div>
                                )}

                                {msg.type === "code" && (
                                    <div>
                                        <div className="code-title">{msg.title}</div>
                                        <pre className="code-box">{msg.code}</pre>
                                    </div>
                                )}

                                {msg.type === "options" && (
                                    <div className={`option-box ${msg.disabled ? "disabled" : ""}`}>
                                        <div className="option-title">{msg.title}</div>
                                        <div className="option-list">
                                            {msg.options.map((o) => (
                                                <button
                                                    key={o.value}
                                                    className="option-btn"
                                                    disabled={msg.disabled || loading}
                                                    onClick={() => handleOptionClick(msg.id, msg.kind, o)}
                                                    title={o.label}
                                                >
                                                    {o.label}
                                                </button>
                                            ))}
                                        </div>
                                    </div>
                                )}
                            </div>
                        </div>
                    ))}

                    {loading && (
                        <div className="msg-row bot">
                            <div className="msg-avatar">🤖</div>
                            <div className="msg-bubble bot">Typing…</div>
                        </div>
                    )}

                    <div ref={chatEndRef} />
                </section>

                <footer className="chatgpt-composer">
                    <div className="input-row">
                        <input
                            className="chat-input"
                            placeholder="Type a message..."
                            value={typedText}
                            onChange={(e) => setTypedText(e.target.value)}
                            onKeyDown={(e) => e.key === "Enter" && isSendEnabled && handleSend()}
                            disabled={loading}
                        />
                        <button
                            className={isSendEnabled ? "send-btn-enabled" : "send-btn"}
                            onClick={handleSend}
                            disabled={!isSendEnabled}
                        >
                            ➤
                        </button>
                    </div>
                </footer>
            </main>
        </div>
    );
}

export default QABotUI;