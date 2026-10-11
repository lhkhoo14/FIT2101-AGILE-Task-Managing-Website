// US-20: change history now lives in the project's record on the server, so this
// file is no longer the store of record. It is kept only so the sprint dashboard
// can lift events that were recorded in this browser before the switchover and
// push them to the API once. Nothing writes to IndexedDB any more.
(function () {
    const DATABASE_NAME = "sprint-dashboard";
    const DATABASE_VERSION = 1;
    const STORE_NAME = "change-history";
    const LEGACY_STORAGE_KEY = "sprint_change_history";
    const MIGRATION_FLAG_KEY = "sprint_change_history_migrated";
    // Claimed before an upload starts so two open tabs cannot both import the
    // same events and duplicate them in the server-side feed.
    const MIGRATION_CLAIM_KEY = "sprint_change_history_migration_started";
    let databasePromise;

    // Keep the old one-time localStorage -> IndexedDB import so nothing is lost.
    function migrateLegacyStorage(database) {
        if (localStorage.getItem(MIGRATION_FLAG_KEY) === "1") return;

        let legacyEntries = [];
        try {
            legacyEntries = JSON.parse(localStorage.getItem(LEGACY_STORAGE_KEY) || "[]");
            if (!Array.isArray(legacyEntries)) legacyEntries = [];
        } catch (_error) {
            legacyEntries = [];
        }
        if (!legacyEntries.length) return;

        try {
            const transaction = database.transaction(STORE_NAME, "readwrite");
            const store = transaction.objectStore(STORE_NAME);
            for (const entry of legacyEntries) {
                const { id, ...storedEntry } = entry;
                store.add(storedEntry);
            }
        } catch (error) {
            console.warn("[Change History] Legacy localStorage import failed.", error);
        }
    }

    function openDatabase() {
        if (databasePromise) return databasePromise;

        databasePromise = new Promise((resolve) => {
            // A browser that blocks IndexedDB, or one that never had the old
            // store, simply has nothing to migrate.
            if (typeof indexedDB === "undefined") {
                resolve(null);
                return;
            }

            const request = indexedDB.open(DATABASE_NAME, DATABASE_VERSION);
            request.onupgradeneeded = () => {
                const database = request.result;
                if (!database.objectStoreNames.contains(STORE_NAME)) {
                    const store = database.createObjectStore(STORE_NAME, {
                        keyPath: "id",
                        autoIncrement: true,
                    });
                    store.createIndex("timestamp", "timestamp");
                }
            };
            request.onsuccess = () => {
                const database = request.result;
                migrateLegacyStorage(database);
                resolve(database);
            };
            request.onerror = () => {
                databasePromise = undefined;
                console.warn("[Change History] No legacy store available.", request.error);
                resolve(null);
            };
        });

        return databasePromise;
    }

    window.sprintHistoryDb = {
        isMigrated() {
            return localStorage.getItem(MIGRATION_FLAG_KEY) === "1";
        },

        // Returns true only for the first caller, so the upload runs once.
        claimMigration() {
            if (this.isMigrated()) return false;
            if (localStorage.getItem(MIGRATION_CLAIM_KEY) === "1") return false;
            localStorage.setItem(MIGRATION_CLAIM_KEY, "1");
            return true;
        },

        markMigrated() {
            localStorage.setItem(MIGRATION_FLAG_KEY, "1");
        },

        async getLegacyEntries() {
            // Read every event still held by the old browser store.
            const database = await openDatabase();
            if (!database || !database.objectStoreNames.contains(STORE_NAME)) return [];

            return new Promise((resolve) => {
                const request = database
                    .transaction(STORE_NAME, "readonly")
                    .objectStore(STORE_NAME)
                    .getAll();
                request.onsuccess = () => resolve(request.result || []);
                request.onerror = () => {
                    console.warn("[Change History] Unable to read legacy events.", request.error);
                    resolve([]);
                };
            });
        },
    };
})();
