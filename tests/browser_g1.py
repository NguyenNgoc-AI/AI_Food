"""Run separately, with requirements-browser.txt and Google Chrome installed."""
from playwright.sync_api import expect, sync_playwright

from live_server import LiveServer


class BrowserG1(LiveServer):
    def test_shared_cookie_and_delayed_refresh(self):
        with sync_playwright() as engine:
            browser = engine.chromium.launch(channel="chrome", headless=True)
            try:
                ctx = browser.new_context()
                def post(path, data):
                    res = ctx.request.post(self.url + "/api" + path, data=data, headers={"X-SmartFood":"1"})
                    self.assertTrue(res.ok, res.status)
                accounts = {}
                for name in ("switch_b", "switch_a"):
                    accounts[name] = {"username":name, "password":"browser-test-only"}
                    post("/auth/register", accounts[name])
                    post("/auth/login", accounts[name])
                    post("/households", {"name":"House " + name})
                old, active = ctx.new_page(), ctx.new_page()
                for page in (old, active):
                    page.goto(self.url + "/household")
                    expect(page.locator("#home-name")).to_have_text("House switch_a")
                old.evaluate("""() => {
                    const fetchNow = window.fetch.bind(window);
                    let delay = true;
                    window.fetch = async (...args) => {
                        const response = await fetchNow(...args);
                        if (delay && args[0] === '/api/households/current') {
                            delay = false;
                            await new Promise(done => { window.releaseOld = done; });
                        }
                        return response;
                    };
                    window.pendingRefresh = refresh();
                }""")
                old.wait_for_function("typeof window.releaseOld === 'function'")
                active.locator("#logout").click()
                expect(old.locator("#account")).to_be_visible()
                active.get_by_label("Tên đăng nhập").fill("switch_b")
                active.get_by_label("Mật khẩu").fill(accounts["switch_b"]["password"])
                active.locator("#auth-submit").click()
                expect(old.locator("#home-name")).to_have_text("House switch_b")
                old.evaluate("window.releaseOld(); window.pendingRefresh")
                expect(old.locator("#home-name")).to_have_text("House switch_b")
                expect(old.locator("#username")).to_have_text("switch_b")
                old.route("**/api/households/current", lambda route: route.abort())
                old.locator("#refresh").click()
                expect(old.locator("#unavailable")).to_be_visible()
                expect(old.locator("#home-name")).to_be_empty()
                expect(old.locator("#members li")).to_have_count(0)
                old.unroute("**/api/households/current")
                old.locator("#retry-session").click()
                expect(old.locator("#home-name")).to_have_text("House switch_b")
                post("/auth/login", accounts["switch_a"])
                mismatch = ctx.request.post(self.url + "/api/auth/logout",
                    headers={"X-SmartFood":"1","X-SmartFood-Actor":str(old.evaluate("user.id"))})
                self.assertEqual(mismatch.status, 409)
                old.evaluate("window.dispatchEvent(new Event('focus'))")
                expect(old.locator("#home-name")).to_have_text("House switch_a")
            finally:
                browser.close()

    def test_household_lifecycle(self):
        with sync_playwright() as engine:
            browser = engine.chromium.launch(channel="chrome", headless=True)
            try:
                def account(username):
                    context = browser.new_context(viewport={"width": 390, "height": 844})
                    p = context.new_page()
                    p.on("dialog", lambda dialog: dialog.accept())
                    p.goto(self.url + "/household")
                    p.locator("#mode").click()
                    p.get_by_label("Tên đăng nhập").fill(username)
                    p.get_by_label("Mật khẩu").fill("browser-test-only")
                    p.locator("#auth-submit").click()
                    expect(p.locator("#notice")).to_contain_text("Đã tạo tài khoản")
                    p.get_by_label("Mật khẩu").fill("browser-test-only")
                    p.locator("#auth-submit").click()
                    expect(p.locator("#onboard")).to_be_visible()
                    return p

                def create(p, name):
                    p.get_by_label("Tên hộ").fill(name)
                    p.get_by_role("button", name="Tạo hộ", exact=True).click()
                    expect(p.locator("#home-name")).to_have_text(name)

                def issue(p):
                    p.locator("#issue").click()
                    expect(p.locator("#code")).to_be_visible()
                    return p.locator("#code").input_value()

                def join(p, code):
                    p.get_by_label("Mã mời từ chủ hộ").fill(code)
                    p.get_by_role("button", name="Tham gia", exact=True).click()

                a,b,c = [account(name) for name in ("owner_a","member_a","owner_b")]
                create(a,"Nhà A")
                create(c,"Nhà B")
                invalid = issue(a)
                a.get_by_role("button", name="Thu hồi").click()
                expect(a.locator("#codes li")).to_have_count(0)
                join(b,invalid)
                expect(b.locator("#notice")).to_contain_text("đã bị thu hồi")
                join(b,issue(a))
                expect(b.locator("#home-name")).to_have_text("Nhà A")
                expect(b.locator("#invites")).to_be_hidden()
                target = c.request.get(self.url + "/api/me").json()["household_id"]
                self.assertEqual(b.request.get(f"{self.url}/api/households/{target}").status,404)
                a.locator("#refresh").click()
                a.get_by_role("button",name="Chuyển quyền").click()
                expect(a.locator("#invites")).to_be_hidden()
                b.locator("#refresh").click()
                expect(b.locator("#invites")).to_be_visible()
                b.get_by_role("button",name="Xóa khỏi hộ").click()
                expect(b.locator("#members li")).to_have_count(1)
                a.locator("#refresh").click()
                expect(a.locator("#onboard")).to_be_visible()
                join(a,issue(b))
                expect(a.locator("#home-name")).to_have_text("Nhà A")
                a.locator("#leave").click()
                expect(a.locator("#onboard")).to_be_visible()
                b.locator("#logout").click()
                expect(b.locator("#account")).to_be_visible()
                self.assertEqual(b.request.get(self.url + "/api/me").status,401)
                expect(c.locator("#home-name")).to_have_text("Nhà B")
                self.assertTrue(c.evaluate("document.documentElement.scrollWidth <= innerWidth"))
            finally:
                browser.close()
