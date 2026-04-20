// ui/ui-app/src/QA_bot_UI.jsx
import React, { useEffect, useMemo, useRef, useState } from "react";
import "./QA_bot_UI.css";

// ✅ normalize backend URL (no trailing slash)
const RAW_API = import.meta.env.VITE_BACKEND_URL || "http://127.0.0.1:5000";
const API = String(RAW_API).replace(/\/+$/, "");

const STEPS = {
    PROJECT: "PROJECT",
    SPRINT: "SPRINT",
    STORY: "STORY",
    CONFIRM_GEN: "CONFIRM_GEN",
    REVIEW_BDD: "REVIEW_BDD",
    REVIEW_LOCATORS: "REVIEW_LOCATORS",
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
    const [refinedFeature, setRefinedFeature] = useState("");

    // ✅ Option-B governance state (MUST be inside component — fixes blank UI issue)
    const [bddDuplicateInfo, setBddDuplicateInfo] = useState(null);
    const [locatorPreview, setLocatorPreview] = useState(null);
    const [locatorDuplicateInfo, setLocatorDuplicateInfo] = useState(null);

    const [testScriptPreview, setTestScriptPreview] = useState(null);      // { scenario_name, sprint_name, story_key, test_script }
    const [testScriptDuplicateInfo, setTestScriptDuplicateInfo] = useState(null); // { path, existing_test_script }

    const newId = () =>
        (typeof crypto !== "undefined" && crypto.randomUUID)
            ? crypto.randomUUID()
            : String(Date.now()) + Math.random().toString(16).slice(2);

    const pushBot = (text) =>
        setMessages((m) => [...m, { id: newId(), role: "bot", type: "text", text }]);

    const pushUser = (text) =>
        setMessages((m) => [...m, { id: newId(), role: "user", type: "text", text }]);

    const pushBotInfo = (title, content) =>
        setMessages((m) => [...m, { id: newId(), role: "bot", type: "info", title, content }]);

    const pushBotCode = (title, code) =>
        setMessages((m) => [...m, { id: newId(), role: "bot", type: "code", title, code }]);

    const pushBotOptions = (title, options, kind) =>
        setMessages((m) => [
            ...m,
            { id: newId(), role: "bot", type: "options", title, options, kind, disabled: false },
        ]);

    const disableOptionsMessage = (msgId) => {
        setMessages((m) => m.map((x) => (x.id === msgId ? { ...x, disabled: true } : x)));
    };

    const pushUserSelection = (kind, option) => {
        const chosen = option?.label || option?.value || "";
        let msg = `You have selected: ${chosen}`;
        if (kind === "project") msg = `You have selected the space ${chosen}`;
        if (kind === "sprint") msg = `You have selected the sprint ${chosen}`;
        if (kind === "story") msg = `You have selected the Story ${chosen}`;
        pushUser(msg);
    };

    useEffect(() => {
        chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
    }, [messages, loading]);

    const showDefaultWelcome = () => {
        pushBot("Welcome to QA Copilot!");
        // pushBot(`ℹ️ UI connected backend URL: ${API}`);
    };

    // ✅ unified fetch helper (no-cache + safer error parsing)
    const apiFetch = async (path, options = {}) => {
        const url = `${API}${path}`;
        const merged = {
            ...options,
            cache: "no-store",
            mode: "cors",
            headers: {
                "Content-Type": "application/json",
                ...(options.headers || {}),
            },
        };

        const res = await fetch(url, merged);

        let data = null;
        const ct = res.headers.get("content-type") || "";
        if (ct.includes("application/json")) {
            try {
                data = await res.json();
            } catch {
                data = null;
            }
        } else {
            try {
                const txt = await res.text();
                data = txt ? { detail: txt } : null;
            } catch {
                data = null;
            }
        }

        return { res, data };
    };

    const checkBackend = async () => {
        try {
            const { res } = await apiFetch("/health", { method: "GET", headers: {} });
            return res.ok;
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
        setRefinedFeature("");

        setBddDuplicateInfo(null);
        setLocatorPreview(null);
        setLocatorDuplicateInfo(null);

        setTestScriptPreview(null);
        setTestScriptDuplicateInfo(null);

        showDefaultWelcome();
        await loadProjects(true);
    };

    const loadProjects = async (silent = false) => {
        setLoading(true);
        try {
            const ok = await checkBackend();
            if (!ok) {
                pushBot(`❌ Backend not reachable at ${API}. Please start FastAPI server and verify /health.`);
                return;
            }

            const { res, data } = await apiFetch("/projects", { method: "GET", headers: {} });
            if (!res.ok) {
                pushBot(`❌ Unable to fetch Spaces (projects). ${data?.detail || "Check /projects endpoint."}`);
                return;
            }

            const list = data?.projects || [];
            if (!silent) pushBot("Please select anyone spaces from below:");
            pushBotOptions(
                "Please select anyone spaces from below:",
                list.map((p) => ({ value: p.key, label: `${p.name} (${p.key})` })),
                "project"
            );
        } catch {
            pushBot("❌ Unable to fetch Spaces (projects). Please check backend /projects endpoint.");
        } finally {
            setLoading(false);
        }
    };

    const loadSprints = async (projectKey) => {
        setLoading(true);
        try {
            const { res, data } = await apiFetch(`/sprints/${projectKey}`, { method: "GET", headers: {} });
            if (!res.ok) {
                pushBot(`❌ Unable to fetch iterations. ${data?.detail || "Check /sprints/{projectKey} endpoint."}`);
                return;
            }

            const list = data?.sprints || [];
            pushBot("Please select available any one sprint from below:");
            pushBotOptions(
                "Please select available any one sprint from below:",
                list.map((s) => ({ value: String(s.id), label: s.name })),
                "sprint"
            );
        } catch {
            pushBot("❌ Unable to fetch iterations. Please check backend /sprints/{projectKey} endpoint.");
        } finally {
            setLoading(false);
        }
    };

    const loadStories = async (sprintId) => {
        setLoading(true);
        try {
            const { res, data } = await apiFetch(`/stories/${sprintId}`, { method: "GET", headers: {} });
            if (!res.ok) {
                pushBot(`❌ Unable to fetch stories. ${data?.detail || "Check /stories/{sprintId} endpoint."}`);
                return;
            }

            const list = data?.stories || [];
            pushBot("Please select available any one story from below:");
            pushBotOptions(
                "Please select available any one story from below:",
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
            `Story Title: ${data.summary}\n` +
            `Story description: ${data.description || "(no description)"}\n\n` +
            `Story details:\n` +
            `  story number: ${data.key}\n` +
            `  Assigned to : ${data.assignee || "-"}`;
        pushBotInfo("User Story Details:", info);
    };

    const loadStoryDetails = async (projectKey, sprintId, storyKey) => {
        setLoading(true);
        try {
            const { res, data } = await apiFetch("/search", {
                method: "POST",
                body: JSON.stringify({ project: projectKey, sprint: sprintId, key: storyKey }),
            });

            if (!res.ok) {
                pushBot(`❌ ${data?.detail || "Failed to fetch story details."}`);
                return;
            }

            setStoryDetails(data);
            showStoryInfoCard(data);

            setStep(STEPS.CONFIRM_GEN);
            pushBot("Do you want to convert the story description into bdd feature format?");
            pushBotOptions(
                "Choose an option",
                [
                    { value: "YES", label: "Yes" },
                    { value: "NO", label: "No" },
                ],
                "yesno_generate"
            );
        } catch {
            pushBot("❌ Error fetching story details.");
        } finally {
            setLoading(false);
        }
    };

    const setAutoRefine = async (enabled) => {
        try {
            await apiFetch("/config/auto_refine", {
                method: "POST",
                body: JSON.stringify({ enabled }),
            });
        } catch {
            // ignore
        }
    };

    const callBlueVerseRefiner = async ({ existingFeature = "" } = {}) => {
        if (!storyDetails) return null;
        setLoading(true);
        try {
            pushBot("Refiner Agent is generating / refining the BDD feature file...");

            const payload = {
                story_key: storyDetails.key,
                summary: storyDetails.summary,
                description: storyDetails.description,
                project: selectedProject?.value || "",
                sprint: selectedSprint?.value || "",
                existing_feature: existingFeature || "",
            };

            const { res, data } = await apiFetch("/blueverse/refine_feature", {
                method: "POST",
                body: JSON.stringify(payload),
            });

            if (!res.ok) {
                pushBot(`❌ Refiner Agent failed: ${data?.detail || "Unknown error"}`);
                return null;
            }

            const featureText =
                typeof data.feature === "string"
                    ? data.feature
                    : data.feature?.refined_feature || "";

            setRefinedFeature(featureText);

            pushBot("Please review and approve the converted BDD test case below:");
            pushBotCode("Converted Test case:", featureText);

            setStep(STEPS.REVIEW_BDD);
            pushBotOptions(
                "Please choose one option:",
                [
                    { value: "APPROVE", label: "Yes I approve" },
                    { value: "REGENERATE", label: "Regenerate the Test case" },
                    { value: "CANCEL", label: "Cancel" },
                ],
                "review_bdd"
            );

            return featureText;
        } catch {
            pushBot("❌ Refiner Agent error. Please try again.");
            return null;
        } finally {
            setLoading(false);
        }
    };

    // ----------------------------
    // Option-B Governance: Save Feature with duplicate scenario handling
    // ----------------------------
    const saveFeatureGoverned = async (decision = "save") => {
        if (!storyDetails || !refinedFeature) return;
        setLoading(true);
        try {
            const { res, data } = await apiFetch("/feature/save", {
                method: "POST",
                body: JSON.stringify({
                    story_key: storyDetails.key,
                    feature_text: refinedFeature,
                    decision,
                }),
            });

            if (!res.ok) {
                pushBot(`❌ Save failed: ${data?.detail || "Unknown error"}`);
                return;
            }

            if (data.status === "DUPLICATE_SCENARIO") {
                setBddDuplicateInfo(data);
                pushBot(`The approved scenario "${data.scenario}" already exists.`);
                pushBotOptions(
                    "Please choose one option:",
                    [
                        { value: "USE_EXISTING", label: "Use exsist scenario" },
                        { value: "OVERWRITE", label: "Yes do overwrite" },
                        { value: "CANCEL", label: "Cancel" },
                    ],
                    "dup_bdd"
                );
                return;
            }

            if (data.status === "SAVED" || data.status === "OVERWRITTEN" || data.status === "USING_EXISTING") {
                pushBot(`✅ Feature approved: ${data.path || ""}`.trim());
                await askGenerateLocatorDetails();
                return;
            }

            pushBot("✅ Feature processed.");
            await askGenerateLocatorDetails();
        } catch {
            pushBot("❌ Save failed due to network/backend error.");
        } finally {
            setLoading(false);
        }
    };

    const saveTestScriptGoverned = async (decision = "save") => {
        if (!testScriptPreview?.test_script || !storyDetails) return;

        setLoading(true);
        try {
            const payload = {
                story_key: testScriptPreview.story_key,
                sprint_name: testScriptPreview.sprint_name,
                scenario_name: testScriptPreview.scenario_name,
                test_script: testScriptPreview.test_script,
                decision, // save | overwrite | reuse_existing | cancel
            };

            const { res, data } = await apiFetch("/feature/testscript/save", {
                method: "POST",
                body: JSON.stringify(payload),
            });

            if (!res.ok) {
                pushBot(`❌ Save test script failed: ${data?.detail || "Unknown error"}`);
                return;
            }

            if (data.status === "DUPLICATE_TEST_SCRIPT") {
                setTestScriptDuplicateInfo(data);

                pushBot(`The approved Test Script already found at: ${data.path}`);
                pushBotCode("Existing Test Script:", data.existing_test_script || "");

                pushBotOptions(
                    "Please choose anyone options from below to proceed it to further.",
                    [
                        { value: "REUSE", label: "Reuse exsist test script" },
                        { value: "OVERWRITE", label: "Yes do overwrite" },
                        { value: "CANCEL", label: "Cancel" },
                    ],
                    "dup_test_script"
                );
                return;
            }

            if (data.status === "TEST_SCRIPT_REUSED") {
                pushBot(`✅ Reused existing test script: ${data.path}`);
                pushBot('The test execution part will be comming soon! Thank you.');
                pushBotOptions("Choose an option", [{ value: "OK", label: "Okay" }], "final_ok");
                return;
            }

            if (data.status === "TEST_SCRIPT_SAVED") {
                pushBot(`✅ Test script saved: ${data.path}`);
                pushBot('The test execution part will be comming soon! Thank you.');
                pushBotOptions("Choose an option", [{ value: "OK", label: "Okay" }], "final_ok");
                return;
            }

            if (data.status === "CANCELLED") {
                pushBot("Cancelled. Restarting from Space selection...");
                await resetConversation();
                return;
            }

            pushBot("✅ Test script decision applied.");
        } catch {
            pushBot("❌ Save test script failed due to network/backend error.");
        } finally {
            setLoading(false);
        }
    };


    const askGenerateLocatorDetails = async () => {
        setStep(STEPS.REVIEW_LOCATORS);
        pushBot(`Do you want to generate a locator details for the approved bdd test case ${storyDetails?.key || ""}?`);
        pushBotOptions(
            "Choose an option",
            [
                { value: "YES", label: "Yes" },
                { value: "NO", label: "No" },
            ],
            "yesno_locators"
        );
    };

    const askGenerateTestScript = async () => {
        pushBot(
            `Do you want to generate test script for created locator details for the scenario ${storyDetails?.key || ""}?`
        );
        pushBotOptions(
            "Choose an option",
            [
                { value: "YES", label: "Yes I want to generate a Test Script" },
                { value: "NO", label: "No I want to generate a Test Script" },
            ],
            "yesno_test_script"
        );
    };

    const generateTestScriptPreview = async () => {
        if (!locatorPreview?.locator_details || !storyDetails) return;

        setLoading(true);
        try {
            const scenarioName = getScenarioNameFromFeature();
            const sprintName = selectedSprint?.label || selectedSprint?.value || "UNKNOWN_SPRINT";

            pushBot(`Generating test script for scenario "${scenarioName}"...`);

            const payload = {
                story_key: storyDetails.key,
                sprint_name: sprintName,
                scenario_name: scenarioName,
                locator_details: locatorPreview.locator_details,
            };

            const { res, data } = await apiFetch("/feature/testscript/generate", {
                method: "POST",
                body: JSON.stringify(payload),
            });

            if (!res.ok) {
                pushBot(`❌ Test script generation failed: ${data?.detail || "Unknown error"}`);
                return;
            }

            const script = (data?.test_script || "").trim();
            if (!script) {
                pushBot("❌ Test script generation returned empty script.");
                return;
            }

            const previewObj = {
                story_key: storyDetails.key,
                sprint_name: sprintName,
                scenario_name: scenarioName,
                test_script: script,
            };

            setTestScriptPreview(previewObj);

            pushBot(`Please review and approve the generated test script for the scenario "${scenarioName}"`);
            pushBotCode("Generated Test Script:", script);

            pushBotOptions(
                "Please choose one option:",
                [
                    { value: "APPROVE", label: "Yes I Approve" },
                    { value: "REGENERATE", label: "Regenerate the test script" },
                    { value: "CANCEL", label: "Cancel" },
                ],
                "review_test_script"
            );
        } catch {
            pushBot("❌ Test script generation failed due to network/backend error.");
        } finally {
            setLoading(false);
        }
    };

    const getScenarioNameFromFeature = () => {
        const text = refinedFeature || "";
        const m = text.match(/^\s*Scenario:\s*(.+)\s*$/im);
        return (m && m[1]) ? m[1].trim() : (storyDetails?.key || "UNKNOWN");
    };

    const generateLocatorPreview = async () => {
        if (!refinedFeature) return;
        setLoading(true);

        try {
            pushBot("Analyzing application UI to generate reusable locator details...");

            const { res, data } = await apiFetch("/feature/locator/preview", {
                method: "POST",
                body: JSON.stringify({ feature_text: refinedFeature }),
            });

            if (!res.ok) {
                pushBot(`❌ Locator preview failed: ${data?.detail || "Unknown error"}`);
                return;
            }

            // ✅ UI SHOULD SHOW ONLY locator_details (hide plans + preview_navigation_ok)
            const locatorDetails = Array.isArray(data?.locator_details) ? data.locator_details : [];

            // Keep state shape stable for saveLocatorDetailsGoverned()
            setLocatorPreview({ locator_details: locatorDetails });

            // ✅ Display ONLY locator_details to user
            pushBotCode("Locator Details (Preview):", JSON.stringify(locatorDetails, null, 2));

            pushBotOptions(
                "Please review and approve the created locator details for the each steps:",
                [
                    { value: "APPROVE", label: "Yes I Approve" },
                    { value: "REGENERATE", label: "Regenerate the Locator details" },
                    { value: "CANCEL", label: "Cancel" },
                ],
                "review_locators"
            );
        } catch {
            pushBot("❌ Locator preview failed due to network/backend error.");
        } finally {
            setLoading(false);
        }
    };

    const saveLocatorDetailsGoverned = async (decision = "save") => {
        if (!locatorPreview?.locator_details) return;
        setLoading(true);
        try {
            const { res, data } = await apiFetch("/feature/locator/save", {
                method: "POST",
                body: JSON.stringify({
                    locator_details: locatorPreview.locator_details,
                    decision,
                }),
            });

            if (!res.ok) {
                pushBot(`❌ Save locators failed: ${data?.detail || "Unknown error"}`);
                return;
            }

            if (data.status === "DUPLICATE_LOCATORS") {
                setLocatorDuplicateInfo(data);
                pushBot("The approved locator details already exsist.");
                pushBotOptions(
                    "Please choose one option:",
                    [
                        { value: "USE_EXISTING", label: "Use exsist locator" },
                        { value: "OVERWRITE", label: "Yes do overwrite" },
                        { value: "CANCEL", label: "Cancel" },
                    ],
                    "dup_locators"
                );
                return;
            }

            if (data.status === "LOCATORS_SAVED") {
                pushBot("✅ Locator details saved successfully.");
                await askGenerateTestScript();
                return;
            }

            if (data.status === "LOCATORS_REUSED") {
                pushBot("✅ Using existing locator details (no overwrite applied).");
                await askGenerateTestScript();
                return;
            }

            if (data.status === "CANCELLED") {
                pushBot("Cancelled. Restarting from Space selection...");
                await resetConversation();
                return;
            }

            pushBot("✅ Locator decision applied.");
            pushBot("Phase complete. Restarting...");
            await resetConversation();
        } catch {
            pushBot("❌ Save locators failed due to network/backend error.");
        } finally {
            setLoading(false);
        }
    };

    const handleOptionClick = async (msgId, kind, option) => {
        if (loading) return;
        disableOptionsMessage(msgId);
        pushUserSelection(kind, option);

        if (kind === "project") {
            setSelectedProject(option);
            setSelectedSprint(null);
            setSelectedStory(null);
            setStoryDetails(null);
            setRefinedFeature("");
            setStep(STEPS.SPRINT);
            await loadSprints(option.value);
            return;
        }

        if (kind === "sprint") {
            setSelectedSprint(option);
            setSelectedStory(null);
            setStoryDetails(null);
            setRefinedFeature("");
            setStep(STEPS.STORY);
            await loadStories(option.value);
            return;
        }

        if (kind === "story") {
            setSelectedStory(option);
            await loadStoryDetails(selectedProject?.value, selectedSprint?.value, option.value);
            return;
        }

        if (kind === "yesno_generate") {
            if (option.value === "YES") {
                await setAutoRefine(true);
                await callBlueVerseRefiner({ existingFeature: "" });
                return;
            }
            if (option.value === "NO") {
                await setAutoRefine(false);
                pushBot("Okay. Restarting from Space selection...");
                await resetConversation();
                return;
            }
        }

        if (kind === "review_bdd") {
            if (option.value === "APPROVE") {
                await saveFeatureGoverned("save");
                return;
            }
            if (option.value === "REGENERATE") {
                await callBlueVerseRefiner({ existingFeature: refinedFeature });
                return;
            }
            if (option.value === "CANCEL") {
                pushBot("Cancelled. Restarting from Space selection...");
                await resetConversation();
                return;
            }
        }

        if (kind === "dup_bdd") {
            if (option.value === "USE_EXISTING") {
                await saveFeatureGoverned("use_existing");
                return;
            }
            if (option.value === "OVERWRITE") {
                await saveFeatureGoverned("overwrite");
                return;
            }
            if (option.value === "CANCEL") {
                pushBot("Cancelled. Restarting from Space selection...");
                await resetConversation();
                return;
            }
        }

        if (kind === "yesno_locators") {
            if (option.value === "YES") {
                await generateLocatorPreview();
                return;
            }
            if (option.value === "NO") {
                pushBot("Okay. Restarting from Space selection...");
                await resetConversation();
                return;
            }
        }

        if (kind === "review_locators") {
            if (option.value === "APPROVE") {
                await saveLocatorDetailsGoverned("save");
                return;
            }
            if (option.value === "REGENERATE") {
                await generateLocatorPreview();
                return;
            }
            if (option.value === "CANCEL") {
                pushBot("Cancelled. Restarting from Space selection...");
                await resetConversation();
                return;
            }
        }

        if (kind === "dup_locators") {
            if (option.value === "USE_EXISTING") {
                await saveLocatorDetailsGoverned("use_existing");
                return;
            }
            if (option.value === "OVERWRITE") {
                await saveLocatorDetailsGoverned("overwrite");
                return;
            }
            if (option.value === "CANCEL") {
                pushBot("Cancelled. Restarting from Space selection...");
                await resetConversation();
                return;
            }
        }

        if (kind === "yesno_test_script") {
            if (option.value === "YES") {
                await generateTestScriptPreview();
                return;
            }
            if (option.value === "NO") {
                pushBot("Cancelled. Restarting from Space selection...");
                await resetConversation();
                return;
            }
        }
        if (kind === "review_test_script") {
            if (option.value === "APPROVE") {
                // ✅ duplicate check happens here via backend save endpoint
                await saveTestScriptGoverned("save");
                return;
            }
            if (option.value === "REGENERATE") {
                await generateTestScriptPreview();
                return;
            }
            if (option.value === "CANCEL") {
                pushBot("Cancelled. Restarting from Space selection...");
                await resetConversation();
                return;
            }
        }
        if (kind === "dup_test_script") {
            if (option.value === "REUSE") {
                await saveTestScriptGoverned("reuse_existing");
                return;
            }
            if (option.value === "OVERWRITE") {
                await saveTestScriptGoverned("overwrite");
                return;
            }
            if (option.value === "CANCEL") {
                pushBot("Cancelled. Restarting from Space selection...");
                await resetConversation();
                return;
            }
        }
        if (kind === "final_ok") {
            if (option.value === "OK") {
                await resetConversation();
                return;
            }
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
        () => [{ text: "Conversation History (Coming Soon)" }, { text: "New Chat (Current)" }],
        []
    );

    const isSendEnabled = !loading && typedText.trim().length > 0;

    const BotAvatar = () => (
        <img
            className="sidebar-img"
            src="/bot.png"
            alt=""
            onError={(e) => {
                e.currentTarget.style.display = "none";
                e.currentTarget.parentNode.insertAdjacentHTML(
                    "afterbegin",
                    '<span style="font-size:24px;vertical-align:middle;">🤖</span>'
                );
            }}
        />
    );

    return (
        <div className="chatgpt-layout">
            <aside className="chatgpt-sidebar">
                <div className="sidebar-top">
                    <div className="sidebar-title-row">
                        <BotAvatar />
                        <div className="sidebar-title-text">Oracle Pythia-26</div>
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
                    <div className="header-title">QA Copilot</div>
                    <div className="header-subtitle">LTM</div>
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
