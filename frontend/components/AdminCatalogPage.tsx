"use client";

import Link from "next/link";
import { ArrowRight } from "lucide-react";
import AdminGate from "@/components/AdminGate";
import AdminCatalogManager from "@/components/AdminCatalogManager";
import { ADMIN_CATALOG_ENTITIES, ADMIN_CATALOG_VIEWS } from "@/lib/adminCatalog";

export default function AdminCatalogPage({ kind }: { kind: string }) {
  const config = ADMIN_CATALOG_VIEWS[kind] ?? ADMIN_CATALOG_ENTITIES[kind];
  return (
    <AdminGate
      title={config?.title ?? "مدیریت نظام آموزشی"}
      description={config?.description ?? "مدیریت کاتالوگ آموزشی درسیار"}
    >
      {({ authHeaders, onUnauthorized }) => (
        <main className="admin-main admin-education-page">
          <div className="admin-catalog-breadcrumb">
            <Link href="/admin/education" className="admin-catalog-back">
              <ArrowRight size={14} /> مدیریت نظام آموزشی و کاتالوگ درسی
            </Link>
          </div>
          <AdminCatalogManager key={kind} kind={kind} authHeaders={authHeaders} onUnauthorized={onUnauthorized} />
        </main>
      )}
    </AdminGate>
  );
}
