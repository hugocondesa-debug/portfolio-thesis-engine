import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { YamlList } from "@/components/yamls/yaml-list";
import { yamlListFixture } from "@/tests/fixtures";

describe("YamlList", () => {
  it("renders one card per yaml", () => {
    render(<YamlList ticker="1846.HK" yamls={yamlListFixture} />);
    expect(screen.getByText("scenarios.yaml")).toBeInTheDocument();
    expect(screen.getByText("capital_allocation.yaml")).toBeInTheDocument();
  });

  it("renders empty state for no yamls", () => {
    render(<YamlList ticker="1846.HK" yamls={[]} />);
    expect(
      screen.getByText(/No editable yamls present/),
    ).toBeInTheDocument();
  });

  it("renders version count", () => {
    render(<YamlList ticker="1846.HK" yamls={yamlListFixture} />);
    expect(screen.getByText(/2 versions/)).toBeInTheDocument();
    expect(screen.getByText(/0 versions/)).toBeInTheDocument();
  });
});
