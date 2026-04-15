import React from "react";
import { Box, FormControl, InputLabel, Select, MenuItem } from "@mui/material";

export default function BotCardSelect({
    label,
    value,
    options,
    onChange,
    getOptionLabel,
    getOptionValue,
}) {
    return (
        <Box mt={2}>
            <FormControl fullWidth size="small">
                <InputLabel sx={{ color: "#cbd5e1" }}>{label}</InputLabel>
                <Select
                    value={value || ""}
                    label={label}
                    onChange={(e) => onChange(e.target.value)}
                    sx={{
                        color: "#e5e7eb",
                        ".MuiOutlinedInput-notchedOutline": { borderColor: "#334155" },
                    }}
                >
                    {options.map((opt) => (
                        <MenuItem key={getOptionValue(opt)} value={getOptionValue(opt)}>
                            {getOptionLabel(opt)}
                        </MenuItem>
                    ))}
                </Select>
            </FormControl>
        </Box>
    );
}
