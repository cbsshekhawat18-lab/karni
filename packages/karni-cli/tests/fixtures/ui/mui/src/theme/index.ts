import { createTheme, alpha } from "@mui/material/styles";
import { blue } from "@mui/material/colors";

const brandMain = "#5b21b6";

// The app's theme.
export const theme = createTheme({
  palette: {
    mode: "light",
    primary: { main: "#5b21b6", contrastText: "#ffffff", light: "#7c3aed" },
    secondary: { main: "#db2777" },
    error: { main: "#b91c1c" },
    background: { default: "#f8fafc", paper: "#ffffff" },
    text: { primary: "#0f172a", secondary: "#64748b" },
    divider: "#e2e8f0",
    info: { main: blue[500] },
    warning: { main: alpha(brandMain, 0.5) },
  },
  shape: { borderRadius: 10 },
  typography: {
    fontFamily: '"Roboto", "Helvetica", "Arial", sans-serif',
    h1: { fontSize: "2.5rem" },
  },
  spacing: 6,
  components: {
    MuiButton: { styleOverrides: { root: { textTransform: "none" } } },
  },
  breakpoints: { values: { xs: 0, sm: 600, md: 900, lg: 1200, xl: 1536 } },
});
