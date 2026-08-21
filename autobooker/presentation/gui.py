import asyncio
import re
import threading
import tkinter.filedialog as fd
from collections.abc import Coroutine
from typing import Any

import customtkinter as ctk
from pydantic import HttpUrl

from autobooker.application.orchestrator import BookingOrchestrator
from autobooker.domain.models import BookingTarget, RunMode, TaskConfig
from autobooker.domain.strategy import AvailableOption, BookingStrategy, FormAction
from autobooker.infrastructure.session_store import SessionStore


class AsyncWorker(threading.Thread):
    def __init__(self) -> None:
        super().__init__(daemon=True)
        self.loop = asyncio.new_event_loop()

    def run(self) -> None:
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def submit(self, coro: Coroutine[Any, Any, Any]) -> None:
        asyncio.run_coroutine_threadsafe(coro, self.loop)


class AutoBookerApp(ctk.CTk):  # type: ignore[misc]
    """GUI mit Tabview, Export/Import, Polling-Settings und Abbruch-Funktion."""

    def __init__(self) -> None:
        super().__init__()
        self.store = SessionStore()
        self.session_data = self.store.load()
        self.worker = AsyncWorker()
        self.worker.start()

        # NEU: Hält die Referenz zum aktuell laufenden Orchestrator
        self.active_orchestrator: BookingOrchestrator | None = None

        self.title("AutoBooker v2.0 - Tactical Checkout")
        self.geometry("750x850")
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.title_font = ctk.CTkFont(size=18, weight="bold")
        self.option_vars: dict[str, tuple[ctk.BooleanVar, AvailableOption]] = {}

        self._build_header()

        self.tabview = ctk.CTkTabview(self)
        self.tabview.pack(padx=20, pady=10, fill="both", expand=True)

        self.tab_workflow = self.tabview.add("Workflow")
        self.tab_settings = self.tabview.add("Einstellungen")

        self._build_workflow_tab()
        self._build_settings_tab()
        self._build_log_console()

        self._load_config_to_ui()

    def _build_header(self) -> None:
        frame = ctk.CTkFrame(self, fg_color="transparent")
        frame.pack(pady=5, fill="x")

        ctk.CTkButton(frame, text="Config Laden (Import)", command=self._import_config).pack(
            side="left", padx=20
        )

        ctk.CTkButton(frame, text="Config Sichern (Export)", command=self._export_config).pack(
            side="right", padx=20
        )

    def _build_workflow_tab(self) -> None:
        frame_calib = ctk.CTkFrame(self.tab_workflow)
        frame_calib.pack(pady=10, fill="x")
        ctk.CTkLabel(frame_calib, text="1: Kalibrierung & Exploration", font=self.title_font).pack(
            pady=5
        )

        ctk.CTkLabel(frame_calib, text="Dummy-Kurs URL:").pack(anchor="w", padx=10)
        self.dummy_url_input = ctk.CTkEntry(frame_calib, width=650)
        self.dummy_url_input.pack(pady=5, padx=10)

        self.btn_explore = ctk.CTkButton(
            frame_calib, text="Exploration starten", command=self._on_explore_clicked
        )
        self.btn_explore.pack(pady=10)

        self.frame_strategy = ctk.CTkFrame(self.tab_workflow)
        self.frame_strategy.pack(pady=10, fill="x")
        ctk.CTkLabel(self.frame_strategy, text="2: Buchungs-Strategie", font=self.title_font).pack(
            pady=5
        )

        self.options_frame = ctk.CTkFrame(self.frame_strategy, fg_color="transparent")
        self.options_frame.pack(pady=5, fill="x")

        frame_arm = ctk.CTkFrame(self.tab_workflow)
        frame_arm.pack(pady=10, fill="x")
        ctk.CTkLabel(frame_arm, text="3: Scharfschalten", font=self.title_font).pack(pady=5)
        ctk.CTkLabel(frame_arm, text="Live-Kurs URL:").pack(anchor="w", padx=10)

        self.target_url_input = ctk.CTkEntry(frame_arm, width=650)
        self.target_url_input.pack(pady=5, padx=10, anchor="w")

        # NEU: Ein Container für die Arm/Cancel Buttons nebeneinander
        btn_container = ctk.CTkFrame(frame_arm, fg_color="transparent")
        btn_container.pack(pady=15, fill="x")

        self.btn_arm = ctk.CTkButton(
            btn_container, text="ARM SYSTEM", fg_color="darkred", command=self._on_arm_clicked
        )
        self.btn_arm.pack(side="left", padx=10, expand=True)

        self.btn_cancel = ctk.CTkButton(
            btn_container, text="ABBRUCH", state="disabled", command=self._on_cancel_clicked
        )
        self.btn_cancel.pack(side="right", padx=10, expand=True)

    def _build_settings_tab(self) -> None:
        frame_cred = ctk.CTkFrame(self.tab_settings)
        frame_cred.pack(pady=10, padx=20, fill="x")

        ctk.CTkLabel(frame_cred, text="Login Daten (Auto-Fill)", font=self.title_font).pack(pady=5)

        ctk.CTkLabel(frame_cred, text="Username/Email:").pack(anchor="w", padx=10)
        self.user_input = ctk.CTkEntry(frame_cred, width=400)
        self.user_input.pack(pady=5, padx=10, anchor="w")

        ctk.CTkLabel(frame_cred, text="Passwort:").pack(anchor="w", padx=10)
        self.pass_input = ctk.CTkEntry(frame_cred, width=400, show="*")
        self.pass_input.pack(pady=5, padx=10, anchor="w")

        frame_poll = ctk.CTkFrame(self.tab_settings)
        frame_poll.pack(pady=10, padx=20, fill="x")
        ctk.CTkLabel(frame_poll, text="Engine Settings", font=self.title_font).pack(pady=5)

        ctk.CTkLabel(frame_poll, text="Polling Intervall (ms):").pack(anchor="w", padx=10)
        self.poll_input = ctk.CTkEntry(frame_poll, width=150)
        self.poll_input.pack(pady=5, padx=10, anchor="w")

        ctk.CTkButton(
            self.tab_settings,
            text="Einstellungen temporär übernehmen",
            command=self._save_ui_state_to_session,
        ).pack(pady=20)

    def _build_log_console(self) -> None:
        self.log_box = ctk.CTkTextbox(self, height=180, state="disabled")
        self.log_box.pack(pady=10, padx=20, fill="both", expand=False)

    def _log_to_gui(self, message: str) -> None:
        def update() -> None:
            self.log_box.configure(state="normal")
            self.log_box.insert("end", f"{message}\n")
            self.log_box.see("end")
            self.log_box.configure(state="disabled")

        self.after(0, update)

    def _export_config(self) -> None:
        self._save_ui_state_to_session()
        file_path = fd.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON Files", "*.json"), ("All Files", "*.*")],
            title="Konfiguration speichern unter...",
        )
        if file_path:
            custom_store = SessionStore(file_path=file_path)
            custom_store.save(self.session_data)
            self._log_to_gui(f"[INFO] Konfiguration gesichert in: {file_path}")

    def _import_config(self) -> None:
        file_path = fd.askopenfilename(
            filetypes=[("JSON Files", "*.json"), ("All Files", "*.*")],
            title="Konfiguration laden...",
        )
        if file_path:
            custom_store = SessionStore(file_path=file_path)
            self.session_data = custom_store.load()
            self.store.save(self.session_data)
            self._load_config_to_ui()
            self._log_to_gui(f"[INFO] Konfiguration geladen aus: {file_path}")

    def _load_config_to_ui(self) -> None:
        self.dummy_url_input.delete(0, "end")
        self.dummy_url_input.insert(0, getattr(self.session_data, "dummy_url", ""))
        self.target_url_input.delete(0, "end")
        self.target_url_input.insert(0, getattr(self.session_data, "live_url", ""))

        self.user_input.delete(0, "end")
        self.user_input.insert(0, getattr(self.session_data, "username", ""))
        self.pass_input.delete(0, "end")
        self.pass_input.insert(0, getattr(self.session_data, "password", ""))
        self.poll_input.delete(0, "end")
        self.poll_input.insert(0, str(getattr(self.session_data, "poll_interval_ms", 500)))

        if getattr(self.session_data, "discovered_options", []):
            self._render_discovered_options()

    def _save_ui_state_to_session(self) -> None:
        self.session_data.dummy_url = self.dummy_url_input.get().strip()
        self.session_data.live_url = self.target_url_input.get().strip()
        self.session_data.username = self.user_input.get().strip()
        self.session_data.password = self.pass_input.get().strip()

        try:
            self.session_data.poll_interval_ms = int(self.poll_input.get().strip())
        except ValueError:
            self.session_data.poll_interval_ms = 500

        self.store.save(self.session_data)

    def _on_explore_clicked(self) -> None:
        self.btn_explore.configure(state="disabled")
        self._save_ui_state_to_session()
        self._log_to_gui("[INFO] Starte Kalibrierung... Bitte warten.")
        self.worker.submit(self._run_exploration_task(self.session_data.dummy_url))

    async def _run_exploration_task(self, url: str) -> None:
        try:
            config = TaskConfig(
                target_url=HttpUrl(url),
                target=BookingTarget(service_id="dummy"),
                mode=RunMode.EXPLORATION,
            )
            orchestrator = BookingOrchestrator(
                config=config, store=self.store, progress_callback=self._log_to_gui
            )
            await orchestrator.run()
            self.session_data = self.store.load()
            self.after(0, self._render_discovered_options)
        except Exception as e:
            self._log_to_gui(f"[ERROR] {e}")
        finally:
            self.after(0, lambda: self.btn_explore.configure(state="normal"))

    def _render_discovered_options(self) -> None:
        for widget in self.options_frame.winfo_children():
            widget.destroy()
        self.option_vars.clear()

        options = getattr(self.session_data, "discovered_options", [])
        if not options:
            ctk.CTkLabel(self.options_frame, text="Keine Personen gefunden.").pack()
            return

        for opt in options:
            var = ctk.BooleanVar(value=False)
            self.option_vars[opt.id] = (var, opt)
            switch = ctk.CTkSwitch(self.options_frame, text=opt.label, variable=var)
            switch.pack(pady=5, padx=20, anchor="w")

        ctk.CTkButton(
            self.options_frame, text="Strategie aus Auswahl generieren", command=self._save_strategy
        ).pack(pady=10)

    def _save_strategy(self) -> None:
        selected_opts = [opt for var, opt in self.option_vars.values() if var.get()]
        if not selected_opts:
            self._log_to_gui("[ERROR] Bitte mindestens eine Person wählen!")
            return

        actions = [FormAction(name="skip_warning", value="0")]
        for opt in selected_opts:
            match = re.search(r"\[(\d+)\]", opt.input_name)
            if match:
                uid = match.group(1)
                actions.extend(
                    [
                        FormAction(name=f"selected_customer_list[{uid}]", value="0"),
                        FormAction(name=f"selected_customer_list[{uid}]", value="1"),
                        FormAction(name=f"customer_note_details[{uid}][valid_for]", value="0"),
                        FormAction(name=f"customer_note_details[{uid}][note]", value=""),
                    ]
                )
            else:
                actions.append(FormAction(name=opt.input_name, value=opt.input_value))

        self.session_data.strategy = BookingStrategy(
            target_url="/de/orders/add_to_cart/course_block_applications/course_block_id/{TARGET_ID}/",
            actions=actions,
        )
        self.store.save(self.session_data)
        self._log_to_gui(f"[INFO] Strategie gesichert ({len(selected_opts)} Person/en).")

    def _on_arm_clicked(self) -> None:
        self._save_ui_state_to_session()
        if not self.session_data.live_url or not self.session_data.strategy.actions:
            self._log_to_gui("[ERROR] Live-URL fehlt oder Strategie nicht kalibriert!")
            return

        self.btn_arm.configure(state="disabled", text="SYSTEM ARMED - POLLING...")
        self.btn_cancel.configure(state="normal")
        self.worker.submit(self._run_live_task(self.session_data.live_url))

    def _on_cancel_clicked(self) -> None:
        """Informiert den aktiven Orchestrator über den asynchronen Abbruch."""
        if self.active_orchestrator:
            self.active_orchestrator.cancel()
            self.btn_cancel.configure(state="disabled", text="Abbrechen...")

    async def _run_live_task(self, live_url: str) -> None:
        try:
            config = TaskConfig(
                target_url=HttpUrl(live_url),
                target=BookingTarget(service_id="dynamic"),
                mode=RunMode.LIVE_ATTEMPT_1,
            )
            self.active_orchestrator = BookingOrchestrator(
                config=config, store=self.store, progress_callback=self._log_to_gui
            )
            await self.active_orchestrator.run()
        except asyncio.CancelledError:
            pass  # Das Logging übernimmt bereits der Orchestrator
        except Exception as e:
            self._log_to_gui(f"[FATAL_ERROR] {e}")
        finally:
            self.active_orchestrator = None

            def reset_btns() -> None:
                self.btn_arm.configure(state="normal", text="ARM SYSTEM")
                self.btn_cancel.configure(state="disabled", text="ABBRUCH")

            self.after(0, reset_btns)
