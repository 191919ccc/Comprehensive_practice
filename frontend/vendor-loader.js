(function () {
    function escapeAttr(value) {
        return String(value || "").replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;");
    }

    const pending = [];

    function loadScript(src) {
        return new Promise((resolve, reject) => {
            const script = document.createElement("script");
            script.src = escapeAttr(src);
            script.async = false;
            script.onload = () => resolve(src);
            script.onerror = () => reject(new Error(`failed to load ${src}`));
            document.head.appendChild(script);
        });
    }

    function writeScript({ local, cdn }) {
        const task = loadScript(local).catch(() => loadScript(cdn));
        pending.push(task);
        return task;
    }

    function ready() {
        return Promise.all(pending);
    }

    window.DashboardVendor = {
        writeScript,
        loadScript,
        ready
    };
})();
