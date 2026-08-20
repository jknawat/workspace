import { BrowserRouter, Routes, Route } from "react-router-dom";
import { AuthProvider } from "./lib/auth-context";
import { I18nProvider } from "./lib/i18n";
import { PublicLayout } from "./components/layout/PublicLayout";
import { PortalLayout } from "./components/layout/PortalLayout";
import { AdminLayout } from "./components/layout/AdminLayout";
import { Home } from "./pages/Home";
import { Quote } from "./pages/Quote";
import { Resources } from "./pages/Resources";
import { ShrinkageCalculator } from "./pages/ShrinkageCalculator";
import { FeatureGuide } from "./pages/FeatureGuide";
import { Terms } from "./pages/Terms";
import { Privacy } from "./pages/Privacy";
import { NotFound } from "./pages/NotFound";
import { Login } from "./pages/portal/Login";
import { Register } from "./pages/portal/Register";
import { Dashboard } from "./pages/portal/Dashboard";
import { Orders } from "./pages/portal/Orders";
import { OrderDetail } from "./pages/portal/OrderDetail";
import { Account } from "./pages/portal/Account";
import { Dashboard as AdminDashboard } from "./pages/admin/Dashboard";
import { Orders as AdminOrders } from "./pages/admin/Orders";
import { OrderDetail as AdminOrderDetail } from "./pages/admin/OrderDetail";
import { Customers as AdminCustomers } from "./pages/admin/Customers";

export default function App() {
  return (
    <BrowserRouter>
      <I18nProvider>
      <AuthProvider>
        <Routes>
          <Route element={<PublicLayout />}>
            <Route path="/" element={<Home />} />
            <Route path="/quote" element={<Quote />} />
            <Route path="/resources" element={<Resources />} />
            <Route path="/resources/shrinkage" element={<ShrinkageCalculator />} />
            <Route path="/resources/features" element={<FeatureGuide />} />
            <Route path="/terms" element={<Terms />} />
            <Route path="/privacy" element={<Privacy />} />
            <Route path="*" element={<NotFound />} />
          </Route>

          <Route path="/portal/login" element={<Login />} />
          <Route path="/portal/register" element={<Register />} />

          <Route path="/portal" element={<PortalLayout />}>
            <Route index element={<Dashboard />} />
            <Route path="orders" element={<Orders />} />
            <Route path="orders/:id" element={<OrderDetail />} />
            <Route path="account" element={<Account />} />
          </Route>

          <Route path="/admin" element={<AdminLayout />}>
            <Route index element={<AdminDashboard />} />
            <Route path="orders" element={<AdminOrders />} />
            <Route path="orders/:id" element={<AdminOrderDetail />} />
            <Route path="customers" element={<AdminCustomers />} />
          </Route>
        </Routes>
      </AuthProvider>
      </I18nProvider>
    </BrowserRouter>
  );
}
