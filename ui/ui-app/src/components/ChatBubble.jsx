import React from "react";
import { Box, Typography, Avatar } from "@mui/material";

export default function ChatBubble({ role, text, children }) {
    const isBot = role === "bot";

    return (
        <Box display="flex" gap={2} mb={2} alignItems="flex-start">
            <Avatar sx={{ bgcolor: isBot ? "#2f80ed" : "#64748b" }}>
                {isBot ? "🤖" : "👤"}
            </Avatar>

            <Box
                sx={{
                    maxWidth: "75%",
                    p: 2,
                    borderRadius: 3,
                    bgcolor: isBot ? "#111827" : "#0b1220",
                    border: "1px solid #1f2a3a",
                }}
            >
                {text && (
                    <Typography sx={{ color: "#e5e7eb", whiteSpace: "pre-wrap" }}>
                        {text}
                    </Typography>
                )}
                {children}
            </Box>
        </Box>
    );
}