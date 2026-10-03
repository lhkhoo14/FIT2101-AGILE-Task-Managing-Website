(function () {
    const DATABASE_NAME = "sprint-dashboard";
    const DATABASE_VERSION = 1;
    const STORE_NAME = "change-history";
    const LEGACY_STORAGE_KEY = "sprint_change_history";
    const MIGRATION_FLAG_KEY = "sprint_change_history_migrated";
    let databasePromise;
    let migrationPromise;

    // Keep sprint change events in a browser database shared by dashboard and sprint pages.
    function openDatabase() {
        if (databasePromise) return databasePromise;

        databasePromise = new Promise((resolve, reject) => {
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
            request.onsuccess = () => resolve(request.result);
            request.onerror = () => {
                databasePromise = undefined;
                reject(request.error || new Error("Unable to open change history database."));
            };
        });

        return databasePromise;
    }

    async function migrateLegacyHistory(database) {
        // Import old localStorage events once so existing activity remains visible.
        if (localStorage.getItem(MIGRATION_FLAG_KEY) === "1") return;
        if (migrationPromise) return migrationPromise;

        migrationPromise = new Promise((resolve, reject) => {
            let legacyEntries = [];
            try {
                legacyEntries = JSON.parse(localStorage.getItem(LEGACY_STORAGE_KEY) || "[]");
                if (!Array.isArray(legacyEntries)) legacyEntries = [];
            } catch (_error) {
                legacyEntries = [];
            }

            const transaction = database.transaction(STORE_NAME, "readwrite");
            const store = transaction.objectStore(STORE_NAME);
            for (const entry of legacyEntries) {
                const { id, ...storedEntry } = entry;
                store.add(storedEntry);
            }
            transaction.oncomplete = () => {
                localStorage.setItem(MIGRATION_FLAG_KEY, "1");
                migrationPromise = undefined;
                resolve();
            };
            transaction.onerror = () => {
                migrationPromise = undefined;
                reject(transaction.error || new Error("Unable to migrate existing change history."));
            };
            transaction.onabort = () => {
                migrationPromise = undefined;
                reject(transaction.error || new Error("Change history migration was interrupted."));
            };
        });

        return migrationPromise;
    }

    async function getDatabase() {
        // Finish the one-time migration before reading or writing change events.
        const database = await openDatabase();
        await migrateLegacyHistory(database);
        return database;
    }

    window.sprintHistoryDb = {
        async add(entry) {
            // Save one event and return its generated IndexedDB key.
            const database = await getDatabase();
            return new Promise((resolve, reject) => {
                const transaction = database.transaction(STORE_NAME, "readwrite");
                const request = transaction.objectStore(STORE_NAME).add(entry);
                request.onsuccess = () => resolve(request.result);
                request.onerror = () => reject(request.error || new Error("Unable to save change history."));
            });
        },

        async getAll() {
            // Read all stored events for the dashboard history view.
            const database = await getDatabase();
            return new Promise((resolve, reject) => {
                const request = database.transaction(STORE_NAME, "readonly").objectStore(STORE_NAME).getAll();
                request.onsuccess = () => resolve(request.result);
                request.onerror = () => reject(request.error || new Error("Unable to load change history."));
            });
        },
    };
})();