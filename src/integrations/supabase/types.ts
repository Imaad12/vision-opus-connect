export type Json =
  | string
  | number
  | boolean
  | null
  | { [key: string]: Json | undefined }
  | Json[]

export type Database = {
  // Allows to automatically instantiate createClient with right options
  // instead of createClient<Database, { PostgrestVersion: 'XX' }>(URL, KEY)
  __InternalSupabase: {
    PostgrestVersion: "14.15"
  }
  public: {
    Tables: {
      audit_logs: {
        Row: {
          action: string
          actor_id: string | null
          actor_name: string | null
          after_data: Json | null
          before_data: Json | null
          created_at: string
          entity_id: string | null
          entity_type: string
          id: string
          summary: string | null
        }
        Insert: {
          action: string
          actor_id?: string | null
          actor_name?: string | null
          after_data?: Json | null
          before_data?: Json | null
          created_at?: string
          entity_id?: string | null
          entity_type: string
          id?: string
          summary?: string | null
        }
        Update: {
          action?: string
          actor_id?: string | null
          actor_name?: string | null
          after_data?: Json | null
          before_data?: Json | null
          created_at?: string
          entity_id?: string | null
          entity_type?: string
          id?: string
          summary?: string | null
        }
        Relationships: []
      }
      company_settings: {
        Row: {
          address: string | null
          city: string | null
          company_name: string
          company_name_ar: string
          cr_number: string | null
          currency: string
          default_vat_rate: number
          email: string | null
          id: string
          phone: string | null
          updated_at: string
          vat_number: string | null
        }
        Insert: {
          address?: string | null
          city?: string | null
          company_name?: string
          company_name_ar?: string
          cr_number?: string | null
          currency?: string
          default_vat_rate?: number
          email?: string | null
          id?: string
          phone?: string | null
          updated_at?: string
          vat_number?: string | null
        }
        Update: {
          address?: string | null
          city?: string | null
          company_name?: string
          company_name_ar?: string
          cr_number?: string | null
          currency?: string
          default_vat_rate?: number
          email?: string | null
          id?: string
          phone?: string | null
          updated_at?: string
          vat_number?: string | null
        }
        Relationships: []
      }
      contacts: {
        Row: {
          created_at: string
          created_by: string | null
          customer_id: string | null
          email: string | null
          id: string
          is_primary: boolean
          mobile: string | null
          name: string
          name_ar: string | null
          notes: string | null
          phone: string | null
          position: string | null
          updated_at: string
        }
        Insert: {
          created_at?: string
          created_by?: string | null
          customer_id?: string | null
          email?: string | null
          id?: string
          is_primary?: boolean
          mobile?: string | null
          name: string
          name_ar?: string | null
          notes?: string | null
          phone?: string | null
          position?: string | null
          updated_at?: string
        }
        Update: {
          created_at?: string
          created_by?: string | null
          customer_id?: string | null
          email?: string | null
          id?: string
          is_primary?: boolean
          mobile?: string | null
          name?: string
          name_ar?: string | null
          notes?: string | null
          phone?: string | null
          position?: string | null
          updated_at?: string
        }
        Relationships: [
          {
            foreignKeyName: "contacts_customer_id_fkey"
            columns: ["customer_id"]
            isOneToOne: false
            referencedRelation: "customers"
            referencedColumns: ["id"]
          },
        ]
      }
      contracts: {
        Row: {
          contract_no: string
          created_at: string
          created_by: string | null
          customer_id: string | null
          end_date: string | null
          id: string
          project_id: string | null
          retention_percent: number
          signed_date: string | null
          start_date: string | null
          status: Database["public"]["Enums"]["contract_status"]
          terms: string | null
          title: string
          updated_at: string
          value: number
          vat_rate: number
        }
        Insert: {
          contract_no?: string
          created_at?: string
          created_by?: string | null
          customer_id?: string | null
          end_date?: string | null
          id?: string
          project_id?: string | null
          retention_percent?: number
          signed_date?: string | null
          start_date?: string | null
          status?: Database["public"]["Enums"]["contract_status"]
          terms?: string | null
          title: string
          updated_at?: string
          value?: number
          vat_rate?: number
        }
        Update: {
          contract_no?: string
          created_at?: string
          created_by?: string | null
          customer_id?: string | null
          end_date?: string | null
          id?: string
          project_id?: string | null
          retention_percent?: number
          signed_date?: string | null
          start_date?: string | null
          status?: Database["public"]["Enums"]["contract_status"]
          terms?: string | null
          title?: string
          updated_at?: string
          value?: number
          vat_rate?: number
        }
        Relationships: [
          {
            foreignKeyName: "contracts_customer_id_fkey"
            columns: ["customer_id"]
            isOneToOne: false
            referencedRelation: "customers"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "contracts_project_id_fkey"
            columns: ["project_id"]
            isOneToOne: false
            referencedRelation: "projects"
            referencedColumns: ["id"]
          },
        ]
      }
      customers: {
        Row: {
          address: string | null
          city: string | null
          code: string | null
          country: string
          cr_number: string | null
          created_at: string
          created_by: string | null
          credit_limit: number
          email: string | null
          id: string
          industry: string | null
          name: string
          name_ar: string | null
          notes: string | null
          owner_id: string | null
          payment_terms_days: number
          phone: string | null
          region: string | null
          status: string
          updated_at: string
          vat_number: string | null
          website: string | null
        }
        Insert: {
          address?: string | null
          city?: string | null
          code?: string | null
          country?: string
          cr_number?: string | null
          created_at?: string
          created_by?: string | null
          credit_limit?: number
          email?: string | null
          id?: string
          industry?: string | null
          name: string
          name_ar?: string | null
          notes?: string | null
          owner_id?: string | null
          payment_terms_days?: number
          phone?: string | null
          region?: string | null
          status?: string
          updated_at?: string
          vat_number?: string | null
          website?: string | null
        }
        Update: {
          address?: string | null
          city?: string | null
          code?: string | null
          country?: string
          cr_number?: string | null
          created_at?: string
          created_by?: string | null
          credit_limit?: number
          email?: string | null
          id?: string
          industry?: string | null
          name?: string
          name_ar?: string | null
          notes?: string | null
          owner_id?: string | null
          payment_terms_days?: number
          phone?: string | null
          region?: string | null
          status?: string
          updated_at?: string
          vat_number?: string | null
          website?: string | null
        }
        Relationships: []
      }
      doc_counters: {
        Row: {
          last_value: number
          prefix: string
          year: number
        }
        Insert: {
          last_value?: number
          prefix: string
          year: number
        }
        Update: {
          last_value?: number
          prefix?: string
          year?: number
        }
        Relationships: []
      }
      documents: {
        Row: {
          approved_at: string | null
          approved_by: string | null
          category: string
          created_at: string
          entity_id: string | null
          entity_type: string | null
          file_name: string | null
          id: string
          mime_type: string | null
          notes: string | null
          project_id: string | null
          size_bytes: number | null
          status: Database["public"]["Enums"]["doc_status"]
          storage_path: string
          supersedes_id: string | null
          title: string
          updated_at: string
          uploaded_by: string
          version: number
        }
        Insert: {
          approved_at?: string | null
          approved_by?: string | null
          category?: string
          created_at?: string
          entity_id?: string | null
          entity_type?: string | null
          file_name?: string | null
          id?: string
          mime_type?: string | null
          notes?: string | null
          project_id?: string | null
          size_bytes?: number | null
          status?: Database["public"]["Enums"]["doc_status"]
          storage_path: string
          supersedes_id?: string | null
          title: string
          updated_at?: string
          uploaded_by?: string
          version?: number
        }
        Update: {
          approved_at?: string | null
          approved_by?: string | null
          category?: string
          created_at?: string
          entity_id?: string | null
          entity_type?: string | null
          file_name?: string | null
          id?: string
          mime_type?: string | null
          notes?: string | null
          project_id?: string | null
          size_bytes?: number | null
          status?: Database["public"]["Enums"]["doc_status"]
          storage_path?: string
          supersedes_id?: string | null
          title?: string
          updated_at?: string
          uploaded_by?: string
          version?: number
        }
        Relationships: [
          {
            foreignKeyName: "documents_project_id_fkey"
            columns: ["project_id"]
            isOneToOne: false
            referencedRelation: "projects"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "documents_supersedes_id_fkey"
            columns: ["supersedes_id"]
            isOneToOne: false
            referencedRelation: "documents"
            referencedColumns: ["id"]
          },
        ]
      }
      expenses: {
        Row: {
          amount: number
          approved_at: string | null
          approved_by: string | null
          category: string
          created_at: string
          description: string
          expense_date: string
          id: string
          project_id: string | null
          status: Database["public"]["Enums"]["approval_status"]
          submitted_by: string
          updated_at: string
          vat_amount: number
        }
        Insert: {
          amount?: number
          approved_at?: string | null
          approved_by?: string | null
          category?: string
          created_at?: string
          description: string
          expense_date?: string
          id?: string
          project_id?: string | null
          status?: Database["public"]["Enums"]["approval_status"]
          submitted_by?: string
          updated_at?: string
          vat_amount?: number
        }
        Update: {
          amount?: number
          approved_at?: string | null
          approved_by?: string | null
          category?: string
          created_at?: string
          description?: string
          expense_date?: string
          id?: string
          project_id?: string | null
          status?: Database["public"]["Enums"]["approval_status"]
          submitted_by?: string
          updated_at?: string
          vat_amount?: number
        }
        Relationships: [
          {
            foreignKeyName: "expenses_project_id_fkey"
            columns: ["project_id"]
            isOneToOne: false
            referencedRelation: "projects"
            referencedColumns: ["id"]
          },
        ]
      }
      invoice_items: {
        Row: {
          created_at: string
          description: string
          id: string
          invoice_id: string
          line_no: number
          line_total: number | null
          quantity: number
          unit: string
          unit_price: number
        }
        Insert: {
          created_at?: string
          description: string
          id?: string
          invoice_id: string
          line_no?: number
          line_total?: number | null
          quantity?: number
          unit?: string
          unit_price?: number
        }
        Update: {
          created_at?: string
          description?: string
          id?: string
          invoice_id?: string
          line_no?: number
          line_total?: number | null
          quantity?: number
          unit?: string
          unit_price?: number
        }
        Relationships: [
          {
            foreignKeyName: "invoice_items_invoice_id_fkey"
            columns: ["invoice_id"]
            isOneToOne: false
            referencedRelation: "invoices"
            referencedColumns: ["id"]
          },
        ]
      }
      invoices: {
        Row: {
          amount_paid: number
          contract_id: string | null
          created_at: string
          created_by: string | null
          currency: string
          customer_id: string | null
          due_date: string | null
          id: string
          invoice_no: string
          issue_date: string
          notes: string | null
          project_id: string | null
          purchase_order_id: string | null
          status: Database["public"]["Enums"]["invoice_status"]
          subtotal: number
          supplier_id: string | null
          total: number
          type: Database["public"]["Enums"]["invoice_type"]
          updated_at: string
          vat_amount: number
          vat_rate: number
        }
        Insert: {
          amount_paid?: number
          contract_id?: string | null
          created_at?: string
          created_by?: string | null
          currency?: string
          customer_id?: string | null
          due_date?: string | null
          id?: string
          invoice_no?: string
          issue_date?: string
          notes?: string | null
          project_id?: string | null
          purchase_order_id?: string | null
          status?: Database["public"]["Enums"]["invoice_status"]
          subtotal?: number
          supplier_id?: string | null
          total?: number
          type?: Database["public"]["Enums"]["invoice_type"]
          updated_at?: string
          vat_amount?: number
          vat_rate?: number
        }
        Update: {
          amount_paid?: number
          contract_id?: string | null
          created_at?: string
          created_by?: string | null
          currency?: string
          customer_id?: string | null
          due_date?: string | null
          id?: string
          invoice_no?: string
          issue_date?: string
          notes?: string | null
          project_id?: string | null
          purchase_order_id?: string | null
          status?: Database["public"]["Enums"]["invoice_status"]
          subtotal?: number
          supplier_id?: string | null
          total?: number
          type?: Database["public"]["Enums"]["invoice_type"]
          updated_at?: string
          vat_amount?: number
          vat_rate?: number
        }
        Relationships: [
          {
            foreignKeyName: "invoices_contract_id_fkey"
            columns: ["contract_id"]
            isOneToOne: false
            referencedRelation: "contracts"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "invoices_customer_id_fkey"
            columns: ["customer_id"]
            isOneToOne: false
            referencedRelation: "customers"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "invoices_project_id_fkey"
            columns: ["project_id"]
            isOneToOne: false
            referencedRelation: "projects"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "invoices_purchase_order_id_fkey"
            columns: ["purchase_order_id"]
            isOneToOne: false
            referencedRelation: "purchase_orders"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "invoices_supplier_id_fkey"
            columns: ["supplier_id"]
            isOneToOne: false
            referencedRelation: "suppliers"
            referencedColumns: ["id"]
          },
        ]
      }
      leads: {
        Row: {
          assigned_to: string | null
          close_reason: string | null
          closed_at: string | null
          contact_id: string | null
          created_at: string
          created_by: string | null
          customer_id: string | null
          description: string | null
          estimated_value: number
          expected_close_date: string | null
          id: string
          probability: number
          source: string | null
          status: Database["public"]["Enums"]["lead_status"]
          title: string
          updated_at: string
        }
        Insert: {
          assigned_to?: string | null
          close_reason?: string | null
          closed_at?: string | null
          contact_id?: string | null
          created_at?: string
          created_by?: string | null
          customer_id?: string | null
          description?: string | null
          estimated_value?: number
          expected_close_date?: string | null
          id?: string
          probability?: number
          source?: string | null
          status?: Database["public"]["Enums"]["lead_status"]
          title: string
          updated_at?: string
        }
        Update: {
          assigned_to?: string | null
          close_reason?: string | null
          closed_at?: string | null
          contact_id?: string | null
          created_at?: string
          created_by?: string | null
          customer_id?: string | null
          description?: string | null
          estimated_value?: number
          expected_close_date?: string | null
          id?: string
          probability?: number
          source?: string | null
          status?: Database["public"]["Enums"]["lead_status"]
          title?: string
          updated_at?: string
        }
        Relationships: [
          {
            foreignKeyName: "leads_contact_id_fkey"
            columns: ["contact_id"]
            isOneToOne: false
            referencedRelation: "contacts"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "leads_customer_id_fkey"
            columns: ["customer_id"]
            isOneToOne: false
            referencedRelation: "customers"
            referencedColumns: ["id"]
          },
        ]
      }
      payments: {
        Row: {
          amount: number
          approved_at: string | null
          approved_by: string | null
          created_at: string
          id: string
          invoice_id: string
          method: string
          notes: string | null
          payment_date: string
          recorded_by: string
          reference: string | null
        }
        Insert: {
          amount: number
          approved_at?: string | null
          approved_by?: string | null
          created_at?: string
          id?: string
          invoice_id: string
          method?: string
          notes?: string | null
          payment_date?: string
          recorded_by?: string
          reference?: string | null
        }
        Update: {
          amount?: number
          approved_at?: string | null
          approved_by?: string | null
          created_at?: string
          id?: string
          invoice_id?: string
          method?: string
          notes?: string | null
          payment_date?: string
          recorded_by?: string
          reference?: string | null
        }
        Relationships: [
          {
            foreignKeyName: "payments_invoice_id_fkey"
            columns: ["invoice_id"]
            isOneToOne: false
            referencedRelation: "invoices"
            referencedColumns: ["id"]
          },
        ]
      }
      profiles: {
        Row: {
          avatar_url: string | null
          created_at: string
          department: string | null
          email: string | null
          employee_no: string | null
          full_name: string
          full_name_ar: string | null
          id: string
          is_active: boolean
          job_title: string | null
          phone: string | null
          preferred_language: string
          updated_at: string
        }
        Insert: {
          avatar_url?: string | null
          created_at?: string
          department?: string | null
          email?: string | null
          employee_no?: string | null
          full_name?: string
          full_name_ar?: string | null
          id: string
          is_active?: boolean
          job_title?: string | null
          phone?: string | null
          preferred_language?: string
          updated_at?: string
        }
        Update: {
          avatar_url?: string | null
          created_at?: string
          department?: string | null
          email?: string | null
          employee_no?: string | null
          full_name?: string
          full_name_ar?: string | null
          id?: string
          is_active?: boolean
          job_title?: string | null
          phone?: string | null
          preferred_language?: string
          updated_at?: string
        }
        Relationships: []
      }
      project_members: {
        Row: {
          created_at: string
          id: string
          project_id: string
          role_label: string | null
          user_id: string
        }
        Insert: {
          created_at?: string
          id?: string
          project_id: string
          role_label?: string | null
          user_id: string
        }
        Update: {
          created_at?: string
          id?: string
          project_id?: string
          role_label?: string | null
          user_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "project_members_project_id_fkey"
            columns: ["project_id"]
            isOneToOne: false
            referencedRelation: "projects"
            referencedColumns: ["id"]
          },
        ]
      }
      projects: {
        Row: {
          code: string
          contract_value: number
          created_at: string
          created_by: string | null
          customer_id: string | null
          description: string | null
          end_date: string | null
          id: string
          location: string | null
          name: string
          name_ar: string | null
          progress_percent: number
          project_manager_id: string | null
          quotation_id: string | null
          start_date: string | null
          status: Database["public"]["Enums"]["project_status"]
          updated_at: string
        }
        Insert: {
          code?: string
          contract_value?: number
          created_at?: string
          created_by?: string | null
          customer_id?: string | null
          description?: string | null
          end_date?: string | null
          id?: string
          location?: string | null
          name: string
          name_ar?: string | null
          progress_percent?: number
          project_manager_id?: string | null
          quotation_id?: string | null
          start_date?: string | null
          status?: Database["public"]["Enums"]["project_status"]
          updated_at?: string
        }
        Update: {
          code?: string
          contract_value?: number
          created_at?: string
          created_by?: string | null
          customer_id?: string | null
          description?: string | null
          end_date?: string | null
          id?: string
          location?: string | null
          name?: string
          name_ar?: string | null
          progress_percent?: number
          project_manager_id?: string | null
          quotation_id?: string | null
          start_date?: string | null
          status?: Database["public"]["Enums"]["project_status"]
          updated_at?: string
        }
        Relationships: [
          {
            foreignKeyName: "projects_customer_id_fkey"
            columns: ["customer_id"]
            isOneToOne: false
            referencedRelation: "customers"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "projects_quotation_id_fkey"
            columns: ["quotation_id"]
            isOneToOne: false
            referencedRelation: "quotations"
            referencedColumns: ["id"]
          },
        ]
      }
      purchase_order_items: {
        Row: {
          created_at: string
          description: string
          id: string
          line_no: number
          line_total: number | null
          purchase_order_id: string
          quantity: number
          received_quantity: number
          unit: string
          unit_price: number
        }
        Insert: {
          created_at?: string
          description: string
          id?: string
          line_no?: number
          line_total?: number | null
          purchase_order_id: string
          quantity?: number
          received_quantity?: number
          unit?: string
          unit_price?: number
        }
        Update: {
          created_at?: string
          description?: string
          id?: string
          line_no?: number
          line_total?: number | null
          purchase_order_id?: string
          quantity?: number
          received_quantity?: number
          unit?: string
          unit_price?: number
        }
        Relationships: [
          {
            foreignKeyName: "purchase_order_items_purchase_order_id_fkey"
            columns: ["purchase_order_id"]
            isOneToOne: false
            referencedRelation: "purchase_orders"
            referencedColumns: ["id"]
          },
        ]
      }
      purchase_orders: {
        Row: {
          approved_at: string | null
          approved_by: string | null
          created_at: string
          created_by: string | null
          currency: string
          expected_delivery: string | null
          id: string
          notes: string | null
          order_date: string
          po_no: string
          project_id: string | null
          received_at: string | null
          status: Database["public"]["Enums"]["po_status"]
          submitted_at: string | null
          subtotal: number
          supplier_id: string | null
          total: number
          updated_at: string
          vat_amount: number
          vat_rate: number
        }
        Insert: {
          approved_at?: string | null
          approved_by?: string | null
          created_at?: string
          created_by?: string | null
          currency?: string
          expected_delivery?: string | null
          id?: string
          notes?: string | null
          order_date?: string
          po_no?: string
          project_id?: string | null
          received_at?: string | null
          status?: Database["public"]["Enums"]["po_status"]
          submitted_at?: string | null
          subtotal?: number
          supplier_id?: string | null
          total?: number
          updated_at?: string
          vat_amount?: number
          vat_rate?: number
        }
        Update: {
          approved_at?: string | null
          approved_by?: string | null
          created_at?: string
          created_by?: string | null
          currency?: string
          expected_delivery?: string | null
          id?: string
          notes?: string | null
          order_date?: string
          po_no?: string
          project_id?: string | null
          received_at?: string | null
          status?: Database["public"]["Enums"]["po_status"]
          submitted_at?: string | null
          subtotal?: number
          supplier_id?: string | null
          total?: number
          updated_at?: string
          vat_amount?: number
          vat_rate?: number
        }
        Relationships: [
          {
            foreignKeyName: "purchase_orders_project_id_fkey"
            columns: ["project_id"]
            isOneToOne: false
            referencedRelation: "projects"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "purchase_orders_supplier_id_fkey"
            columns: ["supplier_id"]
            isOneToOne: false
            referencedRelation: "suppliers"
            referencedColumns: ["id"]
          },
        ]
      }
      quotation_approvals: {
        Row: {
          action: string
          actor_id: string
          comment: string | null
          created_at: string
          id: string
          quotation_id: string
        }
        Insert: {
          action: string
          actor_id?: string
          comment?: string | null
          created_at?: string
          id?: string
          quotation_id: string
        }
        Update: {
          action?: string
          actor_id?: string
          comment?: string | null
          created_at?: string
          id?: string
          quotation_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "quotation_approvals_quotation_id_fkey"
            columns: ["quotation_id"]
            isOneToOne: false
            referencedRelation: "quotations"
            referencedColumns: ["id"]
          },
        ]
      }
      quotation_items: {
        Row: {
          created_at: string
          description: string
          id: string
          line_no: number
          line_total: number | null
          quantity: number
          quotation_id: string
          unit: string
          unit_price: number
        }
        Insert: {
          created_at?: string
          description: string
          id?: string
          line_no?: number
          line_total?: number | null
          quantity?: number
          quotation_id: string
          unit?: string
          unit_price?: number
        }
        Update: {
          created_at?: string
          description?: string
          id?: string
          line_no?: number
          line_total?: number | null
          quantity?: number
          quotation_id?: string
          unit?: string
          unit_price?: number
        }
        Relationships: [
          {
            foreignKeyName: "quotation_items_quotation_id_fkey"
            columns: ["quotation_id"]
            isOneToOne: false
            referencedRelation: "quotations"
            referencedColumns: ["id"]
          },
        ]
      }
      quotations: {
        Row: {
          approved_at: string | null
          approved_by: string | null
          created_at: string
          created_by: string | null
          currency: string
          customer_id: string | null
          discount_amount: number
          id: string
          issue_date: string
          lead_id: string | null
          notes: string | null
          owner_id: string | null
          quote_no: string
          rejected_at: string | null
          rejected_by: string | null
          rejection_reason: string | null
          scope: string | null
          sent_at: string | null
          status: Database["public"]["Enums"]["quotation_status"]
          submitted_at: string | null
          submitted_by: string | null
          subtotal: number
          terms: string | null
          title: string
          total: number
          updated_at: string
          valid_until: string | null
          vat_amount: number
          vat_rate: number
        }
        Insert: {
          approved_at?: string | null
          approved_by?: string | null
          created_at?: string
          created_by?: string | null
          currency?: string
          customer_id?: string | null
          discount_amount?: number
          id?: string
          issue_date?: string
          lead_id?: string | null
          notes?: string | null
          owner_id?: string | null
          quote_no?: string
          rejected_at?: string | null
          rejected_by?: string | null
          rejection_reason?: string | null
          scope?: string | null
          sent_at?: string | null
          status?: Database["public"]["Enums"]["quotation_status"]
          submitted_at?: string | null
          submitted_by?: string | null
          subtotal?: number
          terms?: string | null
          title: string
          total?: number
          updated_at?: string
          valid_until?: string | null
          vat_amount?: number
          vat_rate?: number
        }
        Update: {
          approved_at?: string | null
          approved_by?: string | null
          created_at?: string
          created_by?: string | null
          currency?: string
          customer_id?: string | null
          discount_amount?: number
          id?: string
          issue_date?: string
          lead_id?: string | null
          notes?: string | null
          owner_id?: string | null
          quote_no?: string
          rejected_at?: string | null
          rejected_by?: string | null
          rejection_reason?: string | null
          scope?: string | null
          sent_at?: string | null
          status?: Database["public"]["Enums"]["quotation_status"]
          submitted_at?: string | null
          submitted_by?: string | null
          subtotal?: number
          terms?: string | null
          title?: string
          total?: number
          updated_at?: string
          valid_until?: string | null
          vat_amount?: number
          vat_rate?: number
        }
        Relationships: [
          {
            foreignKeyName: "quotations_customer_id_fkey"
            columns: ["customer_id"]
            isOneToOne: false
            referencedRelation: "customers"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "quotations_lead_id_fkey"
            columns: ["lead_id"]
            isOneToOne: false
            referencedRelation: "leads"
            referencedColumns: ["id"]
          },
        ]
      }
      role_permissions: {
        Row: {
          id: string
          permission: Database["public"]["Enums"]["app_permission"]
          role: Database["public"]["Enums"]["app_role"]
        }
        Insert: {
          id?: string
          permission: Database["public"]["Enums"]["app_permission"]
          role: Database["public"]["Enums"]["app_role"]
        }
        Update: {
          id?: string
          permission?: Database["public"]["Enums"]["app_permission"]
          role?: Database["public"]["Enums"]["app_role"]
        }
        Relationships: []
      }
      suppliers: {
        Row: {
          address: string | null
          category: string | null
          city: string | null
          code: string | null
          contact_name: string | null
          cr_number: string | null
          created_at: string
          created_by: string | null
          email: string | null
          id: string
          name: string
          name_ar: string | null
          notes: string | null
          payment_terms_days: number
          phone: string | null
          rating: number
          status: string
          updated_at: string
          vat_number: string | null
        }
        Insert: {
          address?: string | null
          category?: string | null
          city?: string | null
          code?: string | null
          contact_name?: string | null
          cr_number?: string | null
          created_at?: string
          created_by?: string | null
          email?: string | null
          id?: string
          name: string
          name_ar?: string | null
          notes?: string | null
          payment_terms_days?: number
          phone?: string | null
          rating?: number
          status?: string
          updated_at?: string
          vat_number?: string | null
        }
        Update: {
          address?: string | null
          category?: string | null
          city?: string | null
          code?: string | null
          contact_name?: string | null
          cr_number?: string | null
          created_at?: string
          created_by?: string | null
          email?: string | null
          id?: string
          name?: string
          name_ar?: string | null
          notes?: string | null
          payment_terms_days?: number
          phone?: string | null
          rating?: number
          status?: string
          updated_at?: string
          vat_number?: string | null
        }
        Relationships: []
      }
      user_permissions: {
        Row: {
          created_at: string
          granted: boolean
          id: string
          permission: Database["public"]["Enums"]["app_permission"]
          user_id: string
        }
        Insert: {
          created_at?: string
          granted?: boolean
          id?: string
          permission: Database["public"]["Enums"]["app_permission"]
          user_id: string
        }
        Update: {
          created_at?: string
          granted?: boolean
          id?: string
          permission?: Database["public"]["Enums"]["app_permission"]
          user_id?: string
        }
        Relationships: []
      }
      user_roles: {
        Row: {
          created_at: string
          id: string
          role: Database["public"]["Enums"]["app_role"]
          user_id: string
        }
        Insert: {
          created_at?: string
          id?: string
          role: Database["public"]["Enums"]["app_role"]
          user_id: string
        }
        Update: {
          created_at?: string
          id?: string
          role?: Database["public"]["Enums"]["app_role"]
          user_id?: string
        }
        Relationships: []
      }
      user_scopes: {
        Row: {
          scope: Database["public"]["Enums"]["data_scope"]
          updated_at: string
          user_id: string
        }
        Insert: {
          scope?: Database["public"]["Enums"]["data_scope"]
          updated_at?: string
          user_id: string
        }
        Update: {
          scope?: Database["public"]["Enums"]["data_scope"]
          updated_at?: string
          user_id?: string
        }
        Relationships: []
      }
    }
    Views: {
      [_ in never]: never
    }
    Functions: {
      can: {
        Args: { _perm: Database["public"]["Enums"]["app_permission"] }
        Returns: boolean
      }
      has_full_scope: { Args: never; Returns: boolean }
      has_permission: {
        Args: {
          _perm: Database["public"]["Enums"]["app_permission"]
          _user_id: string
        }
        Returns: boolean
      }
      has_role: {
        Args: {
          _role: Database["public"]["Enums"]["app_role"]
          _user_id: string
        }
        Returns: boolean
      }
      is_project_member: {
        Args: { _project_id: string; _user_id: string }
        Returns: boolean
      }
      next_doc_number: { Args: { _prefix: string }; Returns: string }
      user_scope: {
        Args: { _user_id: string }
        Returns: Database["public"]["Enums"]["data_scope"]
      }
    }
    Enums: {
      app_permission:
        | "customers.view"
        | "customers.create"
        | "customers.edit"
        | "customers.delete"
        | "contacts.view"
        | "contacts.create"
        | "contacts.edit"
        | "contacts.delete"
        | "leads.view"
        | "leads.create"
        | "leads.edit"
        | "leads.assign"
        | "leads.close"
        | "quotations.view"
        | "quotations.create"
        | "quotations.edit"
        | "quotations.submit"
        | "quotations.approve"
        | "quotations.reject"
        | "quotations.send"
        | "quotations.delete"
        | "projects.view"
        | "projects.create"
        | "projects.edit"
        | "projects.archive"
        | "contracts.view"
        | "contracts.create"
        | "contracts.edit"
        | "contracts.delete"
        | "suppliers.view"
        | "suppliers.create"
        | "suppliers.edit"
        | "suppliers.delete"
        | "purchasing.rfq"
        | "purchasing.request"
        | "purchasing.po_create"
        | "purchasing.po_approve"
        | "purchasing.receive"
        | "finance.invoices"
        | "finance.payments"
        | "finance.expenses"
        | "finance.vat"
        | "finance.reports"
        | "documents.view"
        | "documents.upload"
        | "documents.download"
        | "documents.delete"
        | "documents.approve"
        | "documents.versions"
        | "employees.view"
        | "employees.manage"
        | "admin.users"
        | "admin.roles"
        | "admin.settings"
        | "admin.audit"
      app_role:
        | "super_admin"
        | "general_manager"
        | "sales"
        | "estimation"
        | "project_manager"
        | "procurement"
        | "finance"
        | "hr_admin"
        | "document_controller"
        | "employee"
        | "viewer"
      approval_status: "pending" | "approved" | "rejected"
      contract_status:
        | "draft"
        | "active"
        | "suspended"
        | "completed"
        | "terminated"
      data_scope: "all" | "assigned" | "own"
      doc_status:
        | "draft"
        | "pending_approval"
        | "approved"
        | "rejected"
        | "superseded"
      invoice_status:
        | "draft"
        | "issued"
        | "partially_paid"
        | "paid"
        | "overdue"
        | "cancelled"
      invoice_type: "sales" | "purchase"
      lead_status:
        | "new"
        | "qualified"
        | "proposal"
        | "negotiation"
        | "won"
        | "lost"
        | "on_hold"
      po_status:
        | "draft"
        | "pending_approval"
        | "approved"
        | "rejected"
        | "partially_received"
        | "received"
        | "cancelled"
      project_status:
        | "planning"
        | "active"
        | "on_hold"
        | "completed"
        | "archived"
        | "cancelled"
      quotation_status:
        | "draft"
        | "submitted"
        | "approved"
        | "rejected"
        | "sent"
        | "won"
        | "lost"
        | "expired"
    }
    CompositeTypes: {
      [_ in never]: never
    }
  }
}

type DatabaseWithoutInternals = Omit<Database, "__InternalSupabase">

type DefaultSchema = DatabaseWithoutInternals[Extract<keyof Database, "public">]

export type Tables<
  DefaultSchemaTableNameOrOptions extends
    | keyof (DefaultSchema["Tables"] & DefaultSchema["Views"])
    | { schema: keyof DatabaseWithoutInternals },
  TableName extends DefaultSchemaTableNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof (DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"] &
        DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Views"])
    : never = never,
> = DefaultSchemaTableNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? (DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"] &
      DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Views"])[TableName] extends {
      Row: infer R
    }
    ? R
    : never
  : DefaultSchemaTableNameOrOptions extends keyof (DefaultSchema["Tables"] &
        DefaultSchema["Views"])
    ? (DefaultSchema["Tables"] &
        DefaultSchema["Views"])[DefaultSchemaTableNameOrOptions] extends {
        Row: infer R
      }
      ? R
      : never
    : never

export type TablesInsert<
  DefaultSchemaTableNameOrOptions extends
    | keyof DefaultSchema["Tables"]
    | { schema: keyof DatabaseWithoutInternals },
  TableName extends DefaultSchemaTableNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"]
    : never = never,
> = DefaultSchemaTableNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"][TableName] extends {
      Insert: infer I
    }
    ? I
    : never
  : DefaultSchemaTableNameOrOptions extends keyof DefaultSchema["Tables"]
    ? DefaultSchema["Tables"][DefaultSchemaTableNameOrOptions] extends {
        Insert: infer I
      }
      ? I
      : never
    : never

export type TablesUpdate<
  DefaultSchemaTableNameOrOptions extends
    | keyof DefaultSchema["Tables"]
    | { schema: keyof DatabaseWithoutInternals },
  TableName extends DefaultSchemaTableNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"]
    : never = never,
> = DefaultSchemaTableNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"][TableName] extends {
      Update: infer U
    }
    ? U
    : never
  : DefaultSchemaTableNameOrOptions extends keyof DefaultSchema["Tables"]
    ? DefaultSchema["Tables"][DefaultSchemaTableNameOrOptions] extends {
        Update: infer U
      }
      ? U
      : never
    : never

export type Enums<
  DefaultSchemaEnumNameOrOptions extends
    | keyof DefaultSchema["Enums"]
    | { schema: keyof DatabaseWithoutInternals },
  EnumName extends DefaultSchemaEnumNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[DefaultSchemaEnumNameOrOptions["schema"]]["Enums"]
    : never = never,
> = DefaultSchemaEnumNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? DatabaseWithoutInternals[DefaultSchemaEnumNameOrOptions["schema"]]["Enums"][EnumName]
  : DefaultSchemaEnumNameOrOptions extends keyof DefaultSchema["Enums"]
    ? DefaultSchema["Enums"][DefaultSchemaEnumNameOrOptions]
    : never

export type CompositeTypes<
  PublicCompositeTypeNameOrOptions extends
    | keyof DefaultSchema["CompositeTypes"]
    | { schema: keyof DatabaseWithoutInternals },
  CompositeTypeName extends PublicCompositeTypeNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[PublicCompositeTypeNameOrOptions["schema"]]["CompositeTypes"]
    : never = never,
> = PublicCompositeTypeNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? DatabaseWithoutInternals[PublicCompositeTypeNameOrOptions["schema"]]["CompositeTypes"][CompositeTypeName]
  : PublicCompositeTypeNameOrOptions extends keyof DefaultSchema["CompositeTypes"]
    ? DefaultSchema["CompositeTypes"][PublicCompositeTypeNameOrOptions]
    : never

export const Constants = {
  public: {
    Enums: {
      app_permission: [
        "customers.view",
        "customers.create",
        "customers.edit",
        "customers.delete",
        "contacts.view",
        "contacts.create",
        "contacts.edit",
        "contacts.delete",
        "leads.view",
        "leads.create",
        "leads.edit",
        "leads.assign",
        "leads.close",
        "quotations.view",
        "quotations.create",
        "quotations.edit",
        "quotations.submit",
        "quotations.approve",
        "quotations.reject",
        "quotations.send",
        "quotations.delete",
        "projects.view",
        "projects.create",
        "projects.edit",
        "projects.archive",
        "contracts.view",
        "contracts.create",
        "contracts.edit",
        "contracts.delete",
        "suppliers.view",
        "suppliers.create",
        "suppliers.edit",
        "suppliers.delete",
        "purchasing.rfq",
        "purchasing.request",
        "purchasing.po_create",
        "purchasing.po_approve",
        "purchasing.receive",
        "finance.invoices",
        "finance.payments",
        "finance.expenses",
        "finance.vat",
        "finance.reports",
        "documents.view",
        "documents.upload",
        "documents.download",
        "documents.delete",
        "documents.approve",
        "documents.versions",
        "employees.view",
        "employees.manage",
        "admin.users",
        "admin.roles",
        "admin.settings",
        "admin.audit",
      ],
      app_role: [
        "super_admin",
        "general_manager",
        "sales",
        "estimation",
        "project_manager",
        "procurement",
        "finance",
        "hr_admin",
        "document_controller",
        "employee",
        "viewer",
      ],
      approval_status: ["pending", "approved", "rejected"],
      contract_status: [
        "draft",
        "active",
        "suspended",
        "completed",
        "terminated",
      ],
      data_scope: ["all", "assigned", "own"],
      doc_status: [
        "draft",
        "pending_approval",
        "approved",
        "rejected",
        "superseded",
      ],
      invoice_status: [
        "draft",
        "issued",
        "partially_paid",
        "paid",
        "overdue",
        "cancelled",
      ],
      invoice_type: ["sales", "purchase"],
      lead_status: [
        "new",
        "qualified",
        "proposal",
        "negotiation",
        "won",
        "lost",
        "on_hold",
      ],
      po_status: [
        "draft",
        "pending_approval",
        "approved",
        "rejected",
        "partially_received",
        "received",
        "cancelled",
      ],
      project_status: [
        "planning",
        "active",
        "on_hold",
        "completed",
        "archived",
        "cancelled",
      ],
      quotation_status: [
        "draft",
        "submitted",
        "approved",
        "rejected",
        "sent",
        "won",
        "lost",
        "expired",
      ],
    },
  },
} as const
