import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import AuthFlowModal from "@/components/AuthFlowModal";
import { clearCsrfMemo } from "@/lib/apiClient";

type FetchCall = { url: string; init: RequestInit };

function mockFetch(handlers: Record<string, (init: RequestInit) => unknown>) {
  const calls: FetchCall[] = [];
  const fetchMock = vi.fn(async (url: string, init: RequestInit = {}) => {
    calls.push({ url, init });
    const key = `${init.method ?? "GET"} ${url}`;
    const handler = handlers[key] ?? handlers[url];
    if (!handler) {
      return new Response(JSON.stringify({ detail: `unexpected ${key}` }), { status: 404 });
    }
    const result = handler(init);
    if (result instanceof Response) return result;
    return new Response(JSON.stringify(result), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  });
  vi.stubGlobal("fetch", fetchMock);
  return calls;
}

function renderModal(overrides: Partial<React.ComponentProps<typeof AuthFlowModal>> = {}) {
  const onAuthenticated = vi.fn();
  const onClose = vi.fn();
  render(
    <AuthFlowModal
      open
      initialMode="register"
      onClose={onClose}
      onAuthenticated={onAuthenticated}
      {...overrides}
    />
  );
  return { onAuthenticated, onClose };
}

describe("AuthFlowModal — registration", () => {
  beforeEach(() => {
    clearCsrfMemo();
    vi.restoreAllMocks();
  });

  it("walks phone → OTP → password and only creates the account at the end", async () => {
    const user = userEvent.setup();
    let completed = false;
    const calls = mockFetch({
      "POST /api/v1/auth/register/request-otp": () => ({
        phone_number: "09123456789",
        resend_after_seconds: 60,
      }),
      "POST /api/v1/auth/register/verify-otp": () => ({ verified: true, otp_token: "handshake-1" }),
      "POST /api/v1/auth/register/complete": () => {
        completed = true;
        return {
          token: "session-token",
          user: { id: "u1", phone_number: "09123456789", full_name: null },
          csrf_token: "csrf-after-signup",
        };
      },
    });
    const { onAuthenticated, onClose } = renderModal();

    expect(screen.getByRole("heading", { name: "ثبت‌نام با موبایل" })).toBeInTheDocument();

    await user.type(screen.getByPlaceholderText("09123456789"), "09123456789");
    await user.click(screen.getByRole("button", { name: /ارسال کد تأیید/ }));

    await screen.findByText(/کد ۶ رقمی به/);
    expect(calls.map((call) => call.url)).toEqual(["/api/v1/auth/register/request-otp"]);
    expect(screen.queryByLabelText("رمز عبور")).not.toBeInTheDocument();

    await user.type(screen.getByPlaceholderText("123456"), "123456");
    await user.click(screen.getByRole("button", { name: /تأیید کد/ }));

    await screen.findByLabelText("رمز عبور");
    // No account yet: the completion endpoint has not been called.
    expect(completed).toBe(false);

    await user.type(screen.getByLabelText("رمز عبور"), "Secret123");
    await user.type(screen.getByLabelText("تکرار رمز عبور"), "Secret123");
    await user.click(screen.getByRole("button", { name: /تکمیل ثبت‌نام/ }));

    await waitFor(() => expect(onAuthenticated).toHaveBeenCalledWith("session-token", expect.objectContaining({ id: "u1" })));
    expect(onClose).toHaveBeenCalled();
    const completeCall = calls.find((call) => call.url === "/api/v1/auth/register/complete");
    expect(JSON.parse(String(completeCall?.init.body))).toMatchObject({
      phone_number: "09123456789",
      otp_token: "handshake-1",
      password: "Secret123",
      password_confirm: "Secret123",
    });
  });

  it("blocks mismatched passwords without calling the API", async () => {
    const user = userEvent.setup();
    const calls = mockFetch({
      "POST /api/v1/auth/register/request-otp": () => ({ phone_number: "09123456789" }),
      "POST /api/v1/auth/register/verify-otp": () => ({ verified: true, otp_token: "h1" }),
    });
    renderModal();

    await user.type(screen.getByPlaceholderText("09123456789"), "09123456789");
    await user.click(screen.getByRole("button", { name: /ارسال کد تأیید/ }));
    await screen.findByPlaceholderText("123456");
    await user.type(screen.getByPlaceholderText("123456"), "123456");
    await user.click(screen.getByRole("button", { name: /تأیید کد/ }));

    await screen.findByLabelText("رمز عبور");
    await user.type(screen.getByLabelText("رمز عبور"), "Secret123");
    await user.type(screen.getByLabelText("تکرار رمز عبور"), "Secret124");
    await user.click(screen.getByRole("button", { name: /تکمیل ثبت‌نام/ }));

    expect(await screen.findByRole("alert")).toHaveTextContent("یکسان نیست");
    expect(calls.some((call) => call.url.endsWith("/register/complete"))).toBe(false);
  });

  it("surfaces server validation errors and stays on the OTP step", async () => {
    const user = userEvent.setup();
    mockFetch({
      "POST /api/v1/auth/register/request-otp": () =>
        new Response(JSON.stringify({ detail: "کد تأیید منقضی شده است. کد جدید بگیرید." }), { status: 422 }),
    });
    renderModal();

    await user.type(screen.getByPlaceholderText("09123456789"), "09123456789");
    await user.click(screen.getByRole("button", { name: /ارسال کد تأیید/ }));

    expect(await screen.findByRole("alert")).toHaveTextContent("کد تأیید منقضی شده است");
    expect(screen.queryByPlaceholderText("123456")).not.toBeInTheDocument();
  });

  it("shows the demo code only when the API discloses it and fills it on demand", async () => {
    const user = userEvent.setup();
    mockFetch({
      "POST /api/v1/auth/register/request-otp": () => ({ phone_number: "09123456789", demo_code: "654321" }),
    });
    renderModal();

    await user.type(screen.getByPlaceholderText("09123456789"), "09123456789");
    await user.click(screen.getByRole("button", { name: /ارسال کد تأیید/ }));

    await screen.findByText("654321");
    await user.click(screen.getByRole("button", { name: /درج خودکار کد/ }));
    expect(screen.getByPlaceholderText("123456")).toHaveValue("654321");
  });
});

describe("AuthFlowModal — password login and recovery", () => {
  beforeEach(() => {
    clearCsrfMemo();
    vi.restoreAllMocks();
  });

  it("signs in with phone + password and never requests an OTP", async () => {
    const user = userEvent.setup();
    const calls = mockFetch({
      "POST /api/v1/auth/login": () => ({
        token: "login-token",
        user: { id: "u2", phone_number: "09120000000" },
        csrf_token: "csrf-login",
      }),
    });
    const { onAuthenticated } = renderModal({ initialMode: "login" });

    await user.type(screen.getByPlaceholderText("09123456789"), "09120000000");
    await user.type(screen.getByLabelText("رمز عبور"), "Secret123");
    await user.click(screen.getByRole("button", { name: /ورود به حساب/ }));

    await waitFor(() => expect(onAuthenticated).toHaveBeenCalledWith("login-token", expect.objectContaining({ id: "u2" })));
    expect(calls.map((call) => call.url)).toEqual(["/api/v1/auth/login"]);
    expect(calls.some((call) => call.url.includes("otp"))).toBe(false);
  });

  it("shows a wrong-password message without dropping the typed phone number", async () => {
    const user = userEvent.setup();
    mockFetch({
      "POST /api/v1/auth/login": () =>
        new Response(JSON.stringify({ detail: "شماره موبایل یا رمز عبور نادرست است." }), { status: 401 }),
    });
    const { onAuthenticated } = renderModal({ initialMode: "login" });

    await user.type(screen.getByPlaceholderText("09123456789"), "09120000000");
    await user.type(screen.getByLabelText("رمز عبور"), "wrong-pass");
    await user.click(screen.getByRole("button", { name: /ورود به حساب/ }));

    expect(await screen.findByRole("alert")).toHaveTextContent("نادرست است");
    expect(onAuthenticated).not.toHaveBeenCalled();
    expect(screen.getByPlaceholderText("09123456789")).toHaveValue("09120000000");
  });

  it("resets the password through OTP and revokes nothing client-side", async () => {
    const user = userEvent.setup();
    mockFetch({
      "POST /api/v1/auth/password/recover/request-otp": () => ({ phone_number: "09121112233" }),
      "POST /api/v1/auth/password/recover/verify-otp": () => ({ otp_token: "recover-handshake" }),
      "POST /api/v1/auth/password/recover/complete": () => ({ token: "new-session", user: { id: "u3" } }),
    });
    const { onAuthenticated } = renderModal({ initialMode: "recover" });

    await user.type(screen.getByPlaceholderText("09123456789"), "09121112233");
    await user.click(screen.getByRole("button", { name: /ارسال کد تأیید/ }));
    await screen.findByPlaceholderText("123456");
    await user.type(screen.getByPlaceholderText("123456"), "111111");
    await user.click(screen.getByRole("button", { name: /تأیید کد/ }));

    await screen.findByLabelText("رمز عبور");
    await user.type(screen.getByLabelText("رمز عبور"), "BrandNew1");
    await user.type(screen.getByLabelText("تکرار رمز عبور"), "BrandNew1");
    await user.click(screen.getByRole("button", { name: /ثبت رمز عبور جدید/ }));

    await waitFor(() => expect(onAuthenticated).toHaveBeenCalledWith("new-session", expect.objectContaining({ id: "u3" })));
  });

  it("switches modes without losing the typed phone number", async () => {
    const user = userEvent.setup();
    mockFetch({});
    renderModal({ initialMode: "login" });

    const phoneInput = screen.getByPlaceholderText("09123456789");
    await user.type(phoneInput, "09125556677");
    await user.click(screen.getByRole("tab", { name: "بازیابی رمز عبور" }));

    expect(screen.getByRole("heading", { name: "بازیابی رمز عبور" })).toBeInTheDocument();
    expect(screen.getByPlaceholderText("09123456789")).toHaveValue("09125556677");
  });
});
