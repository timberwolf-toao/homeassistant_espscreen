# Working instructions for LLMs and developers

ESP Screens turns ESP32 touch screens into Home Assistant control panels. Four parts, one product:

- **Firmware**: `packages/core.yaml` (the shared UI, every board) plus the C++ in `components/smart_display/`.
- **Boards**: `boards.yaml` is the catalog of every board that ships (key, name, status stable/new/experimental).
  Each board has one file under `packages/boards/` with its hardware and sizes, nothing else.
- **Add-on**: `screen_manager/` (ESP Screen Manager, Python), which stores the tiles and sends them to the screens.
- **Editor**: `web/` (Vue 3 + Vite, TypeScript), which shows a screen while you build its pages.

A screen gets its tiles from the add-on while it runs: every card works in every cell of every page (one tile per
cell, at most eight pages and 64 tiles), the board's grid decides how many fit (docs/RESPONSIVE.md), and no Home
Assistant entity belongs in a board file. docs/README.md lists every doc and says which ones are recipes.

## Where to start for a change

| You want to | Read first | The source of truth |
|---|---|---|
| support a new entity type, or a new control on a tile | docs/CATALOGUE.md | `catalogue/<type>.yaml`, `catalogue/_ha.json` |
| add a screen setting | docs/SETTINGS.md | `settings_screen.h`, `SETTING_RULES` in `screen_manager/app/core.py` |
| add a board | docs/ADDING_A_BOARD.md, then docs/BOARD_RELEASES.md | `boards.yaml`, `packages/boards/<file>.yaml` |
| change sizes, fonts or the grid | docs/RESPONSIVE.md | `ui_scale.h`, `packages/looks/`, `packages/cells/` |
| change a colour | docs/THEME.md | `components/smart_display/theme.h` |
| change how pages are kept or prepared | docs/KEPT_PAGES.md, docs/PAGES.md | `kept_pages.h`, `page_protocol.h` |
| add or change a text | docs/TRANSLATING.md | `screen_manager/translations/en.json` |
| touch the YAML package layers | docs/PROFILES.md | `packages/`, `checkout/` |
| know which test proves what | docs/TESTING.md | `tools/check.sh` |
| publish | docs/RELEASING.md, docs/BOARD_RELEASES.md | `screen_manager/config.yaml`, `tools/affected_boards.py` |

Each recipe ends with the list of places a change of that kind touches. Follow it; a check fails on most you forget.

## How the YAML is put together

A screen's entry is `packages/<key>.yaml` (a screen installed from ESP Screens, over GitHub) or `checkout/<key>.yaml`
(a build from a clone). Both are written by `tools/generate_entries.py` from `boards.yaml`: don't edit them. An entry
includes `packages/core.yaml` and the board file. The board file includes its hardware (`packages/hardware/`), its
look (`packages/looks/standard.yaml` or `compact.yaml`, sizes in mm scaled by the glass's density), its features
(`packages/features/`) and the cards of its grid (`packages/cells/<count>.yaml`, written by `tools/generate_cells.py`).
What the add-on and the editor know of a board is `screen_manager/app/boards.json`, written by
`tools/generate_board_shapes.py`. A board-dependent number is a `${NAME}` in the board file, board-only code inside a
shared lambda is a hook substitution there, and `tools/check_packages.py` keeps every board complete. YAML files in the
root of a working copy (`cyd-2432s028.yaml`, `guition-wallbox.yaml`, ...) are git-ignored local profiles of one
person's screens: never edit, build or ship them as if they were the product.

## Rules the code keeps

Most of these are guarded by a test; the test names the doc to read when it fails.

- **Capabilities come from the catalogue.** What a tile of each entity type can do lives in `catalogue/<type>.yaml`,
  generated into the add-on, the editor and the firmware by `tools/generate_catalogue.py`, with Home Assistant's own
  facts read from its source by `tools/read_ha_source.py` into `catalogue/_ha.json`. A type exists only where it has a
  file, and only after the firmware draws it. Never write a capability rule (a feature bit, an allowed control, a
  firmware gate for an option) by hand in the add-on, the editor or the firmware: use the generated constants.
- **Home Assistant is the reference.** Actions, state words, icons, names and feature support follow Home Assistant
  one to one. Read its source (a sparse clone of home-assistant/core or its frontend) before inventing anything.
- **Behaviour lives once.** Shared UI in `packages/core.yaml` and `components/smart_display`; a board file holds
  hardware and sizes only. A size decision in C++ goes through `ui::px()`/`ui::mm()` and the class through
  `ui::large()`, never through a pixel count of the glass or a board's name.
- **A fixed set of fonts.** Every board has the same font ids, sized by its look (docs/RESPONSIVE.md, "Fonts"). A new
  card takes the largest step that fits instead of bringing a size of its own: every font costs flash, and the 4 MB
  boards (the CYD first) are close to their budget.
- **Colours live in one table**, `components/smart_display/theme.h`. Every role has a light and a dark value, board
  files name paints (`styles: paint_card`), firmware code asks for a role (`theme::color(theme::INK)`). Never write a
  hex colour anywhere else; `tests/test_theme.py` holds the few allowed exceptions.
- **Settings live in one table.** `settings_screen.h` draws the settings page and `SETTING_RULES` in the add-on
  validates the same keys. Every writer goes through `settings_screen::set()`, and the add-on changes a setting through
  the entities in `SETTING_ENTITIES`, never through the layout message. Never widen the eleven-key `settings` block
  older firmware insists on.
- **One editor, the firmware's numbers.** The editor's mockup ports the firmware's sizes to TypeScript
  (`web/src/model/`); a parity test compares them with the C++, so change both or the check fails. The WASM preview
  (`web/wasm/`, docs/EMULATOR_ARCHITECTURE.md) is the real firmware code.
- **Compatibility.** Preserve the data schema, protocol compatibility, unique keys and screen preferences. Test updates
  against existing data (`tests/test_compat_0431.py` keeps every layout saved by 0.4.31). Don't publish an unknown
  storage version without a migration. Future protocol extensions are negotiated, as with `tile_sizes`, never another
  protocol break; legacy delivery stays in the add-on, never as a second decoder on the screen.
- **Kept pages** (docs/KEPT_PAGES.md): a card is drawn only while it is on the glass, a card set is exchanged whole,
  and what a kept page lacks follows from change numbers (`kept_pages::Changes`), never from flags handed around.
- **Memory.** Never walk the PSRAM heap (`heap_caps_get_largest_free_block`, `heap_caps_get_info`) while an RGB panel
  is lit: it shifts a frame. Pictures share one budget worked out from the board's PSRAM. The firmware check gates the
  flash use of every 4 MB board.
- **Touch and navigation.** Keep fixed pages: the page bar appears only when there is more than one page, and free
  scrolling stays out unless it is tested on real glass. Keep the touch filter and the event guard before actions;
  calibration works on filtered raw values, and the affine correction is applied once, never in both the driver and
  the UI. The default standby is at least 600 seconds.
- **The editor** is `web/src`; `screen_manager/app/static` is its build output: run `cd web && npm test && npm run
  build` and commit both. Keep every URL the page asks for relative (`api/...`) so it works behind ingress.
- Production ingress needs no long-lived token or public port.

## Checks

`tools/check.sh` is the gate, locally and in CI; docs/TESTING.md says what each layer proves.

- Every code change: `tools/check.sh` (Python and C++ tests, package and generator checks, translations, the editor's
  tests, types and build, the WASM preview tests and the layout audit of every card on every board shape).
- A firmware change: also `tools/check.sh --firmware --affected`. A change that reaches one board or a few builds only
  those; a change that reaches every board builds `SAMPLE` in `tools/profiles.py` (four boards that differ in chip,
  flash and glass), and CI builds every board nightly. On the packages' older `min_version` ESPHome the same
  `--affected` build is the CYD alone (`MIN_VERSION_SAMPLE`), plus a board for each changed file the CYD doesn't
  build. Renders use `RENDER_SAMPLE`, the smallest, a middle and the largest glass (`tools/check.sh --render
  --sample`), and run by hand.
- A firmware change makes the committed WASM preview stale: `web/wasm/build.sh` rebuilds it, or CI's preview job does
  after the push.
- Firmware tests and hardware acceptance are different checks: report which ones actually ran.

## Releases

Every push of code to main is a release: bump the add-on version in `screen_manager/config.yaml` with a CHANGELOG
entry, otherwise Home Assistant offers no update. Docs-only changes may go out without one. Run
`tools/affected_boards.py` first: it says whether the change reaches no screen, a new board, some boards or every board,
and prints the firmware number, the CHANGELOG heading and the checks. The firmware number is X.Y.Z: Y counts the core
(a shared release is the next X.Y.0) and Z a board's own revision on it (`tools/firmware_count.py` holds the rule). A
new board takes no firmware number. docs/BOARD_RELEASES.md is the recipe, docs/RELEASING.md the rest.

## Installing a screen and working with hardware

The preferred route for new users is docs/EASY_SETUP.md: ESP Screen Manager plus remote ESPHome packages, no token or
blueprint. Tiles live in the add-on's data; Wi-Fi, API and OTA stay in the screen's own ESPHome YAML.

1. Install from ESP Screens: the add-on writes the screen's own YAML with its name, Wi-Fi reference and unique keys,
   and flashes it over USB. Identify the USB port and board first, and check whether a profile for this screen
   already exists; never overwrite a working one. The add-on builds with the ESPHome in `screen_manager/Dockerfile`;
   the packages also build with their `min_version` (`packages/core.yaml`). Don't show keys in logs or chat.
2. Touch: a resistive board (the CYD) shows its calibration on first boot and someone taps the crosshairs;
   `tools/calibrate.py` with docs/CALIBRATING.md is the USB route. Capacitive boards report pixels and need none
   (GT911: `tools/verify_gt911.py`). Only a person can tap the glass; an agent cannot replace that with software
   coordinates, and a successful build is not a flash.
3. Pair with Home Assistant through the ESPHome integration. Read real entity ids and attributes; don't make up
   entities, and don't run real device actions without the owner's permission.
4. Per board, docs/<BOARD>.md has the hardware notes. Display support never configures relays or other peripherals
   on the board.

- No automatic firmware upload to an arbitrary connected port: with several boards, first find the intended port.
- Builds with the same `DEVICE_NAME` share `.esphome/build/<name>`: never compile or upload them at the same time.
  Check the `firmware.bin` path in the upload log and the compile time via `device_info`.
- `diagnostics/run_ui_test.py` renders without Home Assistant actions (don't touch the screen meanwhile; `--name` for
  the expected device). `diagnostics/send_layout.py` pushes a demo layout with every card type; the add-on restores the
  real one within about 25 s. `tools/render/run.py` renders the real firmware of a board on the host, without a screen.
- Share through Git. Don't stage secrets, measurements, binaries, logs, build caches or local profiles.
- Historical diagnostics are background, not proof that a new panel works. Never claim a physical test that wasn't
  performed.

## Writing README and docs text

README.md, README_EXTENDED.md and everything under docs/ ship to production and are public: people across the open
source community read them. Write plain English. Never quote the owner or anyone else, in any language. Don't name the
owner, or use names, IPs, MAC addresses, entity ids or other strings tied to one person's setup; use generic examples.
Don't use em dashes; write a plain comma, period, or "and"/"but" instead. docs/ holds current rules and recipes, not
test logs: what a release changed goes in `screen_manager/CHANGELOG.md` and its release notes.

## Replying to issues and pull requests

A reply on GitHub goes out under the project owner's own account, so every comment on an issue or a pull request ends
with the same signature: a blank line, a `---` rule, and two italic lines, each its own paragraph.

```
---

_Got a screen running? Tell others which board you have and what works on the [Tessera website](https://tessera-maxgramser.on-forge.com/community/share?type=installation). It helps everyone pick a screen that works._

_Like my work? Consider [buying me a coffee](https://buymeacoffee.com/f5j9jnkmhpv), much appreciated!_
```

When the thread is about one board, append `&board=<key>` to that link, with the board's key from boards.yaml (`cyd`,
`guition`, `waveshare43`, ...): the website uses the same keys and opens the report for that board. Keep the blank line
above the `---`. Without it, markdown reads the rule as underlining and turns the last line of the reply into a heading
instead of drawing a separator. The signature belongs under comments only, never in commit messages, release notes,
the README or the docs, where the button under the title already does this.

## Owner's machine

On the owner's machine, git-ignored `.esphome/owner-access.md` says how to reach their Home Assistant and screens for
lookups and tests. If that file is missing you are not on the owner's machine: ask, don't guess.
