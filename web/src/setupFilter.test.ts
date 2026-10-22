import { describe, expect, it } from "vitest";
import { triggerChip } from "./setupFilter";

describe("triggerChip", () => {
  it("is null while the setup is awaiting its trigger", () => {
    expect(triggerChip({ triggered: false, live: false, trigger: 310.53 })).toBeNull();
    expect(triggerChip({ triggered: null })).toBeNull();
  });

  it("says when the week in progress broke the trigger", () => {
    expect(triggerChip({ triggered: true, live: true, trigger: 310.53 })).toEqual({
      label: "triggered this week",
      title: "This week's high traded above the trigger 310.53 (set by last completed week)",
    });
    expect(triggerChip({ triggered: true, live: false, trigger: 9 })?.label).toBe("triggered");
    expect(triggerChip({ triggered: true })?.label).toBe("triggered");
  });

});
