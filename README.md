# Saturday Multiverse

**A living shore. Infinite doors. Your next adventure is waiting.**

Saturday Multiverse is an open-source, self-hostable tabletop-inspired role-playing game where exploration begins on a mysterious shore and expands into adventures beyond the doors of the Beam. Wander the world, discover portals, roll dice, and experience stories narrated by an AI Game Master—while the game engine remains responsible for the rules.

> **Project status:** Milestone 1 has been built and tested locally. The GitHub repository currently contains project documentation and licensing; the application source has not yet been published here.

## The experience

You arrive on the **Living Shore**, an atmospheric, explorable place between worlds. Waves roll in, weather shifts, the campfire flickers, and a lighthouse sweeps the coast with a beam that casts no shadow. Follow the Beam, choose a glowing door, and step into another story.

### Milestone 1 highlights

- **Explore the Living Shore:** A browser-based animated canvas scene with interactive hotspots, tides, weather, surf, lantern-lit landmarks, and an eerie lighthouse.
- **Choose your portal:** The Beam connects the shore to adventures and other worlds.
- **Play an original adventure:** *The Salt-Grave Signal*, a supernatural-horror scenario with four scenes, mysteries, and meaningful choices.
- **AI Game Master:** AI provides narration and atmosphere while deterministic game code handles rules and outcomes.
- **Persistent local state:** SQLite-backed game data for a self-hosted experience.
- **Lightweight architecture:** Python/Flask backend and a no-build browser frontend.
- **Cross-platform launchers:** The Milestone 1 build includes `run.sh` for Linux and `run.bat` for Windows.

## Design principles

**Rules belong to the game, not the model.** The AI Game Master can describe events and respond creatively, but it does not get to invent or override mechanics.

**The world should feel alive.** The shore is more than a menu: it is a place to explore before choosing an adventure.

**Self-hosting matters.** A small, understandable stack makes it practical to run and develop without a large frontend toolchain.

**Portals make room for expansion.** The same central shore can eventually connect many different adventures, genres, and worlds.

## Technology

| Layer | Technology |
| --- | --- |
| Game server | Python + Flask |
| Browser interface | HTML, CSS, JavaScript, Canvas, SVG |
| Persistence | SQLite |
| AI | Narration-only Game Master integration |
| Packaging | Linux and Windows run scripts |

## Installation

The application files have **not yet been published to this repository**. After the Milestone 1 source is uploaded, this section will document the tested setup and launch instructions for Linux and Windows.

The completed local build uses Flask and provides `run.sh` and `run.bat`. Do not expect a working installation from the current documentation-only repository.

## Roadmap

- [x] Build the Living Shore and interactive landmarks
- [x] Add the Beam and adventure portals
- [x] Create the original *Salt-Grave Signal* adventure
- [x] Separate AI narration from game rules
- [x] Implement Flask + SQLite foundation
- [ ] Publish and verify Milestone 1 source in this repository
- [ ] Add verified Linux and Windows installation instructions
- [ ] Expand the adventure and portal library
- [ ] Explore multiplayer support

## Contributing

Ideas, feedback, bug reports, adventures, and improvements are welcome. Once the source is published, use GitHub Issues to discuss proposals or report problems.

## License

Licensed under the [MIT License](LICENSE).

---

**Created by [Kayock](https://github.com/kayock).**  
*Saturday Multiverse — every door is another story.*
