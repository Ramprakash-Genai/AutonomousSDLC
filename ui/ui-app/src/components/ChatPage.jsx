import React, { useEffect, useState } from "react";
import { Box, Typography, Divider, CircularProgress } from "@mui/material";
import ChatBubble from "./ChatBubble";
import BotCardSelect from "./BotCardSelect";
import { fetchSpaces, fetchIterations, fetchStories } from "../api/jiraApi";

export default function ChatPage() {
    const [messages, setMessages] = useState([]);

    const [spaces, setSpaces] = useState([]);
    const [iterations, setIterations] = useState([]);
    const [stories, setStories] = useState([]);

    const [selectedSpace, setSelectedSpace] = useState("");
    const [selectedIteration, setSelectedIteration] = useState("");
    const [selectedStory, setSelectedStory] = useState("");

    const [loading, setLoading] = useState({ spaces: false, iterations: false, stories: false });

    // Step 1: Load spaces at startup
    useEffect(() => {
        initConversation();
        loadSpaces();
    }, []);

    const initConversation = () => {
        setMessages([
            { role: "bot", type: "text", text: "Select the available spaces from Jira:" }
        ]);
    };

    async function loadSpaces() {
        setLoading((p) => ({ ...p, spaces: true }));
        try {
            const data = await fetchSpaces();
            setSpaces(data);
            // Show dropdown prompt
            setMessages((prev) => [
                ...prev,
                { role: "bot", type: "spaces" }
            ]);
        } catch (e) {
            setMessages((prev) => [
                ...prev,
                { role: "bot", type: "text", text: "❌ Unable to fetch spaces. Check backend API." }
            ]);
        } finally {
            setLoading((p) => ({ ...p, spaces: false }));
        }
    }

    async function onSpaceSelected(spaceId) {
        setSelectedSpace(spaceId);
        const spaceObj = spaces.find((s) => s.id === spaceId || s.key === spaceId);

        setMessages((prev) => [
            ...prev,
            { role: "user", type: "text", text: `Selected space: ${spaceObj?.name || spaceId}` },
            { role: "bot", type: "text", text: "Select the available Iteration:" }
        ]);

        // reset downstream
        setSelectedIteration("");
        setSelectedStory("");
        setIterations([]);
        setStories([]);

        setLoading((p) => ({ ...p, iterations: true }));
        try {
            const itData = await fetchIterations(spaceId);
            setIterations(itData);
            setMessages((prev) => [...prev, { role: "bot", type: "iterations" }]);
        } catch (e) {
            setMessages((prev) => [
                ...prev,
                { role: "bot", type: "text", text: "❌ Unable to fetch iterations for this space." }
            ]);
        } finally {
            setLoading((p) => ({ ...p, iterations: false }));
        }
    }

    async function onIterationSelected(iterationId) {
        setSelectedIteration(iterationId);
        const itObj = iterations.find((i) => i.id === iterationId || i.key === iterationId);

        setMessages((prev) => [
            ...prev,
            { role: "user", type: "text", text: `Selected iteration: ${itObj?.name || iterationId}` },
            { role: "bot", type: "text", text: "Select the available stories:" }
        ]);

        // reset downstream
        setSelectedStory("");
        setStories([]);

        setLoading((p) => ({ ...p, stories: true }));
        try {
            const stData = await fetchStories(iterationId);
            setStories(stData);
            setMessages((prev) => [...prev, { role: "bot", type: "stories" }]);
        } catch (e) {
            setMessages((prev) => [
                ...prev,
                { role: "bot", type: "text", text: "❌ Unable to fetch stories for this iteration." }
            ]);
        } finally {
            setLoading((p) => ({ ...p, stories: false }));
        }
    }

    function onStorySelected(storyId) {
        setSelectedStory(storyId);
        const stObj = stories.find((s) => s.id === storyId || s.key === storyId);

        setMessages((prev) => [
            ...prev,
            { role: "user", type: "text", text: `Selected story: ${stObj?.title || stObj?.summary || storyId}` },
            { role: "bot", type: "text", text: "✅ Story selected. Next step: Generate BDD / Refine / Run (we will add next)." }
        ]);
    }

    return (
        <Box sx={{ display: "flex", height: "100vh", bgcolor: "#0b0d10", color: "#e5e7eb" }}>
            <Box sx={{ flex: 1, p: 3, overflowY: "auto" }}>
                <Typography variant="h4" fontWeight="bold">
                    Autonomous SDLC Assistance
                </Typography>
                <Typography variant="subtitle1" sx={{ color: "#9ca3af" }}>
                    Jira User Story → Gherkin Feature Generator
                </Typography>

                <Divider sx={{ my: 2, borderColor: "#1f2937" }} />

                {messages.map((m, idx) => (
                    <ChatBubble key={idx} role={m.role} text={m.type === "text" ? m.text : null}>
                        {m.type === "spaces" && (
                            <>
                                {loading.spaces && <CircularProgress size={18} />}
                                {!loading.spaces && (
                                    <BotCardSelect
                                        label="Jira Space"
                                        value={selectedSpace}
                                        options={spaces}
                                        onChange={onSpaceSelected}
                                        getOptionLabel={(x) => x.name || x.key || x.id}
                                        getOptionValue={(x) => x.id || x.key}
                                    />
                                )}
                            </>
                        )}

                        {m.type === "iterations" && (
                            <>
                                {loading.iterations && <CircularProgress size={18} />}
                                {!loading.iterations && (
                                    <BotCardSelect
                                        label="Iteration"
                                        value={selectedIteration}
                                        options={iterations}
                                        onChange={onIterationSelected}
                                        getOptionLabel={(x) => x.name || x.title || x.id}
                                        getOptionValue={(x) => x.id || x.key}
                                    />
                                )}
                            </>
                        )}

                        {m.type === "stories" && (
                            <>
                                {loading.stories && <CircularProgress size={18} />}
                                {!loading.stories && (
                                    <BotCardSelect
                                        label="Story"
                                        value={selectedStory}
                                        options={stories}
                                        onChange={onStorySelected}
                                        getOptionLabel={(x) => x.title || x.summary || x.key || x.id}
                                        getOptionValue={(x) => x.id || x.key}
                                    />
                                )}
                            </>
                        )}
                    </ChatBubble>
                ))}
            </Box>
        </Box>
    );
}