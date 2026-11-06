import { afterEach, describe, expect, it, vi } from "vitest";
import { softwareApi } from "./api";

afterEach(() => vi.unstubAllGlobals());

describe("software discovery API paths", () => {
  it("calls the implemented repository search endpoint with encoded query and source", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ results: [] }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await softwareApi.searchWingetRepository("Firefox & VLC", "winget");

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/software/discovery/search?query=Firefox%20%26%20VLC&source=winget",
      expect.objectContaining({ credentials: "include" }),
    );
  });

  it("imports a discovered package through the existing catalog import endpoint", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ created: true }), { status: 201 }));
    vi.stubGlobal("fetch", fetchMock);
    const body = { package_id: "Mozilla.Firefox", source: "winget", supported_scopes: ["MACHINE"] as Array<"MACHINE" | "USER"> };

    await softwareApi.importWingetPackage(body);

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/software/discovery/import",
      expect.objectContaining({ method: "POST", body: JSON.stringify(body), credentials: "include" }),
    );
  });
});
