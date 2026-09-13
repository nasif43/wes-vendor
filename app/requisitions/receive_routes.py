
@router.get("/{req_id}/receive", response_class=HTMLResponse)
async def receive_requisition_form(
    req_id: str,
    request: Request,
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Requisition).where(Requisition.id == req_id))
    req = result.scalar_one_or_none()
    if not req:
        await db.commit()
    return RedirectResponse(url="/requisitions", status_code=303)
    
    # We allow QC_RECEIVER, ADMIN, MANAGEMENT
    if user.role not in [UserRole.ADMIN, UserRole.MANAGEMENT, UserRole.QC_RECEIVER]:
        await db.commit()
    return RedirectResponse(url=f"/requisitions/{req_id}", status_code=303)

    from app.decisions.models import Decision
    dec = await db.execute(select(Decision).where(Decision.requisition_id == req_id))
    dec_obj = dec.scalar_one_or_none()
    if not dec_obj or dec_obj.work_order_status != 'approved':
        await db.commit()
    return RedirectResponse(url=f"/requisitions/{req_id}?error=Work+order+not+approved", status_code=303)


    return templates.TemplateResponse(
        request,
        "requisitions/receive.html",
        {"req": req, "user": user}
    )

@router.post("/{req_id}/receive")
async def receive_requisition_submit(
    req_id: str,
    request: Request,
    invoice_number: str = Form(...),
    invoice_url: str = Form(""),
    delivery_image_url: str = Form(""),
    qc_done: bool = Form(False),
    user: UserProfile = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Requisition).where(Requisition.id == req_id))
    req = result.scalar_one_or_none()
    if not req:
        await db.commit()
    return RedirectResponse(url="/requisitions", status_code=303)

    if user.role not in [UserRole.ADMIN, UserRole.MANAGEMENT, UserRole.QC_RECEIVER]:
        await db.commit()
    return RedirectResponse(url=f"/requisitions/{req_id}", status_code=303)

    from app.decisions.models import Decision
    dec = await db.execute(select(Decision).where(Decision.requisition_id == req_id))
    dec_obj = dec.scalar_one_or_none()
    if not dec_obj or dec_obj.work_order_status != 'approved':
        await db.commit()
    return RedirectResponse(url=f"/requisitions/{req_id}?error=Work+order+not+approved", status_code=303)

        
    req.invoice_number = invoice_number
    req.invoice_url = invoice_url
    req.delivery_image_url = delivery_image_url
    req.qc_done = qc_done
    
    if qc_done:
        req.qc_done_by = user.id
        req.qc_done_at = datetime.now(UTC)
        req.status = RequisitionStatus.CLOSED
    else:
        req.status = RequisitionStatus.RECEIVED
        
    await db.flush()
    await db.commit()
    return RedirectResponse(url=f"/requisitions/{req_id}?success=Order+marked+as+received", status_code=303)
