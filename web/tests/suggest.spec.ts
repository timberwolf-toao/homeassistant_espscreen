// The command field of Send command (GitHub #117): a remote's commands under the field, narrowed by what is typed,
// picked with a click or the keys, and anything else typed still goes.
import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import UiSuggest from "../src/components/ui/UiSuggest.vue";

const ROKU = ["home", "reverse", "forward", "play", "select", "volume_down", "volume_up", "volume_mute", "input_hdmi1", "power"];
const items = (wrapper: ReturnType<typeof mount>) => wrapper.findAll('[role="option"]').map((item) => item.text());

describe("UiSuggest", () => {
  it("shows the commands only while the field has the cursor", async () => {
    const wrapper = mount(UiSuggest, { props: { modelValue: "", suggestions: ROKU } });
    expect(wrapper.find('[role="listbox"]').isVisible()).toBe(false);
    await wrapper.find("input").trigger("focus");
    expect(items(wrapper)).toEqual(ROKU);
    await wrapper.find("input").trigger("blur");
    expect(wrapper.find('[role="listbox"]').isVisible()).toBe(false);
  });

  it("narrows by what is typed, a word's start first, case and _ ignored", async () => {
    const wrapper = mount(UiSuggest, { props: { modelValue: "VOL", suggestions: ROKU } });
    await wrapper.find("input").trigger("focus");
    expect(items(wrapper)).toEqual(["volume_down", "volume_up", "volume_mute"]);
    await wrapper.setProps({ modelValue: "mute" });
    expect(items(wrapper)).toEqual(["volume_mute"]);
    await wrapper.setProps({ modelValue: "hdmi" });
    expect(items(wrapper)).toEqual(["input_hdmi1"]);
  });

  it("picks with a click or with the arrows and Enter, and keeps typed text as it is", async () => {
    const wrapper = mount(UiSuggest, { props: { modelValue: "", suggestions: ROKU } });
    const input = wrapper.find("input");
    await input.trigger("focus");
    await wrapper.findAll('[role="option"]')[3].trigger("click");
    expect(wrapper.emitted("pick")?.[0]).toEqual(["play"]);
    await input.trigger("focus");
    await input.trigger("keydown", { key: "ArrowDown" });
    await input.trigger("keydown", { key: "Enter" });
    expect(wrapper.emitted("pick")?.[1]).toEqual(["reverse"]);
    await input.setValue("b64:JgBQAAABKZIUEhQ");
    expect(wrapper.emitted("update:modelValue")?.at(-1)).toEqual(["b64:JgBQAAABKZIUEhQ"]);
  });

  it("hides the list once the field holds one of its values exactly", async () => {
    const wrapper = mount(UiSuggest, { props: { modelValue: "power", suggestions: ROKU } });
    await wrapper.find("input").trigger("focus");
    expect(wrapper.find('[role="listbox"]').isVisible()).toBe(false);
  });
});
