---
fase: 2
estado: vigente
tags: [modelo-de-datos]
---
# Modelo de datos de la fase 2

```mermaid
erDiagram
    Warehouse ||--o{ Stock : ""
    Item ||--o{ Stock : ""
    Item ||--o{ StockMovement : "kardex"
    Item ||--o{ Lot : "lotes"
    MenuItem ||--o{ RecipeLine : "receta"
    RecipeLine }o--|| Item : "insumo"
    Requisition ||--o{ RequisitionLine : ""
    Requisition ||--o{ Quotation : ""
    Quotation }o--|| Supplier : ""
    PurchaseOrder }o--|| Supplier : ""
    PurchaseOrder ||--o{ PurchaseOrderLine : ""
    PurchaseOrder ||--o{ GoodsReceipt : ""
    Supplier ||--o{ SupplierInvoice : "cuentas por pagar"
    Asset ||--o{ WorkOrder : ""
    Asset ||--o{ PreventivePlan : ""
    WorkOrder ||--o| RoomBlock : "bloquea"
    WorkOrder ||--o{ WorkOrderPart : "repuestos"
    Reservation ||--o{ ServiceRequest : ""
    Reservation ||--o| Survey : ""
    Reservation ||--o{ OnlinePayment : ""
```

| App | Modelos |
| --- | --- |
| `inventory` | Warehouse, ItemCategory, Item, Stock (costo promedio por almacén), Lot, StockMovement (kardex), StockCount, StockCountLine, Waste, RecipeLine |
| `purchasing` | Supplier, Requisition, RequisitionLine, Quotation, QuotationLine, PurchaseOrder, PurchaseOrderLine, GoodsReceipt, SupplierInvoice |
| `maintenance` | Asset (activos fijos y equipos), WorkOrder, WorkOrderPart, PreventivePlan |
| `payments` | OnlinePayment (solo token, marca y últimos 4 dígitos) |
| `portal` | ServiceRequest, Survey, Complaint (libro de reclamaciones) |
| Cambios | Reservation.precheckin_at, Outlet.warehouse, MinibarItem.inventory_item |
