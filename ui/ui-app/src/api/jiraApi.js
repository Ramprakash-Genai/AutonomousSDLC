import { api } from "./client";

// Update these endpoints to match your backend if names differ
export async function fetchSpaces() {
    const res = await api.get("/jira/spaces");
    return res.data;
}

export async function fetchIterations(spaceId) {
    const res = await api.get("/jira/iterations", { params: { space: spaceId } });
    return res.data;
}

export async function fetchStories(iterationId) {
    const res = await api.get("/jira/stories", { params: { iteration: iterationId } });
    return res.data;
}
