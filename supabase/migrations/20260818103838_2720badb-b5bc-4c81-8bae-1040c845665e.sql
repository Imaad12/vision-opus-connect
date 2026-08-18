
CREATE POLICY "docs_read" ON storage.objects FOR SELECT TO authenticated
  USING (bucket_id = 'documents' AND (public.can('documents.view') OR public.can('documents.download')));
CREATE POLICY "docs_upload" ON storage.objects FOR INSERT TO authenticated
  WITH CHECK (bucket_id = 'documents' AND public.can('documents.upload') AND owner = auth.uid());
CREATE POLICY "docs_update" ON storage.objects FOR UPDATE TO authenticated
  USING (bucket_id = 'documents' AND (owner = auth.uid() OR public.can('documents.versions')))
  WITH CHECK (bucket_id = 'documents');
CREATE POLICY "docs_delete" ON storage.objects FOR DELETE TO authenticated
  USING (bucket_id = 'documents' AND public.can('documents.delete'));
