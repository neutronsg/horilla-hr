window.tailwind.config = {
  theme: {
    colors: {
      white: '#FFFFFF',
      primary: {
        50: '#f6f6f6',
        100: '#eef1fb',
        200: '#f5f7fd',
        300: '#eef1fb',
        400: '#e3e9ff',
        500: '#cad5fc',
        600: '#051c97',
        700: '#041778',
        800: '#03125f',
        900: '#020c40',
      },

      dark: {
        50: '#E6E6E6',
        100: '#A8A8A8',
        200: '#515151',
        300: '#0b0d12',
        400: '#64748B',
        500: '#190906',
        600: '#000000',
      },

      secondary: {
        50: '#f8fafc',
        100: '#f1f5f9',
        200: '#e2e8f0',
        300: '#cbd5e1',
        400: '#e3e9ff',
        500: '#cad5fc',
        600: '#051c97',
        700: '#334155',
        800: '#1e293b',
        900: '#0f172a',
      },
      success: {
        light: "#86efac",
        DEFAULT: "#22c55e",
        dark: "#15803d",
      },
      warning: {
        light: "#fde68a",
        DEFAULT: "#f59e0b",
        dark: "#b45309",
      },
      danger: {
        light: "#fca5a5",
        DEFAULT: "#ef4444",
        dark: "#b91c1c",
      },

      brand: {
        200: '#f5f7fd',
        300: '#eef1fb',
        500: '#cad5fc',
        600: '#051c97',
        700: '#041778',
        800: '#03125f',
      },

      color: {
        600: '#374151',
      },
    },
    extend: {
      boxShadow: {
        card: "0px 0px 10px rgba(0, 0, 0, 0.05)",
      },
      spacing: {
        18: "4.5rem",
        72: "18rem",
        84: "21rem",
        96: "24rem",
      },
      borderRadius: {
        "4xl": "2rem",
        "5xl": "2.5rem",
      },
      fontSize: {
        xxs: "0.625rem",
      },
      height: {
        "screen-50": "50vh",
        "screen-75": "75vh",
      },
    },
  },
};
