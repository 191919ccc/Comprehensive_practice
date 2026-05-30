(function () {
    function escapeAttr(value) {
        return String(value || "").replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;");
    }

    function writeScript({ local, cdn }) {
        const localSrc = escapeAttr(local);
        const cdnSrc = escapeAttr(cdn);
        document.write(`<script src="${localSrc}" onerror="this.onerror=null;this.src='${cdnSrc}'"><\/script>`);
    }

    window.DashboardVendor = {
        writeScript
    };
})();
